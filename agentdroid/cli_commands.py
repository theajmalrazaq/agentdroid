"""Subcommand handlers for the AgentDroid CLI."""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from agentdroid.adb import AdbDevice
from agentdroid.cli_output import _print_output
from agentdroid.helper import INPUT_DAEMON_PORT, AccessibilityHelperClient
from agentdroid.installer import install_agent_skills_and_rules, run_one_command_setup
from agentdroid.pipeline import CompoundPipeline, PipelineSpec
from agentdroid.security import (
    is_safe_mode_enabled,
    parse_shell_allowlist,
    verify_bundled_helper_apk,
)
from agentdroid.watcher import LiveWatcher

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve_safe_args(args: argparse.Namespace) -> tuple[bool, list[str]]:
    safe_flag = bool(getattr(args, "safe", False))
    safe = is_safe_mode_enabled(True if safe_flag else None)
    raw_allow = getattr(args, "shell_allowlist", None)
    allowlist = list(parse_shell_allowlist(raw_allow if raw_allow else None))
    return safe, allowlist


def cmd_run(args: argparse.Namespace) -> int:
    from agentdroid.cli_parser import _parse_ui_actions

    clear_pkgs = list(args.clear_data or [])
    if args.clear_installed:
        clear_pkgs.append("auto")

    launch_target = args.launch
    if args.launch_installed and not launch_target:
        launch_target = "auto"

    watch_mode = bool(args.watch)
    headless_mode = not watch_mode
    safe_mode, shell_allowlist = _resolve_safe_args(args)

    spec = PipelineSpec(
        serial=args.serial,
        headless=headless_mode,
        watch=watch_mode,
        watch_width=getattr(args, "window_width", 412),
        watch_height=getattr(args, "window_height", 892),
        always_on_top=not getattr(args, "no_always_on_top", False),
        watch_borderless=bool(getattr(args, "borderless", False)),
        watch_interactive=bool(getattr(args, "interactive", False)),
        auto_provision=not args.no_provision,
        install_apks=list(args.install or []),
        grant_all_permissions=not args.no_grant,
        grant_packages=list(args.grant or []),
        clear_packages=clear_pkgs,
        launch_target=launch_target,
        stop_after=bool(args.stop_after),
        push_files=list(args.push or []),
        pull_files=list(args.pull or []),
        open_urls=list(args.open_url or []),
        set_clipboard=args.set_clipboard,
        get_clipboard=bool(args.get_clipboard),
        read_notifications=bool(args.notifications),
        pre_shell=list(args.pre_shell or []),
        ui_actions=_parse_ui_actions(args),
        post_shell=list(args.post_shell or []),
        wait_for_text=list(args.wait_text or []),
        assert_texts=list(args.assert_text or []),
        locked_app_package=args.locked_app,
        safe_mode=safe_mode,
        shell_allowlist=shell_allowlist,
        check_crashes=not args.no_check_crashes,
        collect_logs=bool(args.collect_logs),
        log_lines=args.log_lines,
        screenshot_path=args.screenshot,
        dump_ui=bool(args.dump_ui),
    )

    report: dict[str, Any] | None = None
    if headless_mode and os.environ.get("AGENTDROID_NO_DAEMON") != "1":
        from agentdroid.daemon import run_via_daemon

        report = run_via_daemon(spec)
    if report is None:
        pipeline = CompoundPipeline(spec)
        report = pipeline.run()
    _print_output(report, as_json=bool(args.json))
    return 0 if report.get("ok") else 1


def cmd_watch(args: argparse.Namespace) -> int:
    adb = AdbDevice(serial=args.serial)
    if not adb.connect(timeout=15.0):
        print(f"Error: Could not connect to device {adb.serial}", file=sys.stderr)
        return 1

    if args.headless:
        print(
            json.dumps(
                {
                    "event": "watch_started",
                    "mode": "headless",
                    "device": adb.serial,
                    "foreground": adb.foreground_app(),
                }
            ),
            flush=True,
        )
        try:
            last_fg = None
            while True:
                fg = adb.foreground_app()
                if fg != last_fg:
                    print(
                        json.dumps({"event": "foreground_changed", "data": fg}),
                        flush=True,
                    )
                    last_fg = fg
                time.sleep(2.0)
        except KeyboardInterrupt:
            return 0

    watcher = LiveWatcher(
        adb.serial,
        watch=True,
        interactive_control=bool(args.interactive),
        always_on_top=not getattr(args, "no_always_on_top", False),
        window_width=getattr(args, "window_width", 412),
        window_height=getattr(args, "window_height", 892),
        borderless=bool(getattr(args, "borderless", False)),
    )
    info = watcher.start()
    print(
        f"[agentdroid:watch] Watching {adb.serial} via {info.get('viewer')}. Press Ctrl+C to exit.",
        file=sys.stderr,
    )
    try:
        while True:
            if (
                watcher._scrcpy_proc is not None
                and watcher._scrcpy_proc.poll() is not None
            ):
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        watcher.stop(force=True)
    return 0


def cmd_up(args: argparse.Namespace) -> int:
    compose_file = REPO_ROOT / "docker-compose.yml"
    if not compose_file.is_file():
        print(f"Error: docker-compose.yml not found at {compose_file}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    if args.image:
        env["REDROID_IMAGE"] = args.image

    cmd = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
    if args.build:
        cmd.append("--build")
    cmd.append("redroid")

    if not args.json:
        print("[agentdroid:up] Starting AgentDroid Redroid container...", file=sys.stderr)
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=env, check=False)
    if res.returncode != 0:
        return res.returncode

    adb = AdbDevice(serial=args.serial or f"127.0.0.1:{env.get('REDROID_ADB_PORT', '5555')}")
    prov = adb.provision_silent(force=True, quiet=bool(args.json or args.headless))

    watcher_info = None
    if args.watch:
        watcher = LiveWatcher(
            adb.serial,
            watch=True,
            interactive_control=bool(getattr(args, "interactive", False)),
            always_on_top=not getattr(args, "no_always_on_top", False),
            window_width=getattr(args, "window_width", 412),
            window_height=getattr(args, "window_height", 892),
            borderless=bool(getattr(args, "borderless", False)),
        )
        watcher_info = watcher.start()

    out = {
        "ok": bool(prov.get("provisioned")),
        "device": adb.serial,
        "provision": prov,
        "watch": watcher_info,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"✅ AgentDroid device {adb.serial} is online and silently provisioned.")
    return 0 if out["ok"] else 1


def cmd_down(args: argparse.Namespace) -> int:
    compose_file = REPO_ROOT / "docker-compose.yml"
    cmd = ["docker", "compose", "-f", str(compose_file), "down"]
    if args.volumes:
        cmd.append("-v")
    res = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False)
    return res.returncode


def cmd_provision(args: argparse.Namespace) -> int:
    adb = AdbDevice(serial=args.serial)
    prov = adb.provision_silent(force=bool(args.force), quiet=bool(args.json))
    helper = AccessibilityHelperClient(adb)
    ping = helper.ping()
    out = {
        "ok": bool(prov.get("provisioned")),
        "device": adb.serial,
        "provision": prov,
        "helper": ping,
    }
    if args.json:
        print(json.dumps(out, indent=2))
    else:
        st = "✅ Provisioned" if out["ok"] else "✖ Failed"
        helper_st = "active" if ping else "unreachable"
        print(f"{st} {adb.serial} (Artemis Accessibility Helper: {helper_st})")
    return 0 if out["ok"] else 1


def cmd_app(args: argparse.Namespace) -> int:
    safe_mode, shell_allowlist = _resolve_safe_args(args)
    adb = AdbDevice(
        serial=args.serial,
        safe_mode=True if safe_mode else None,
        shell_allowlist=shell_allowlist if shell_allowlist else None,
    )
    action = args.app_action

    if action == "search":
        hits = adb.search_fdroid_apps(args.target, limit=10)
        if args.json:
            print(json.dumps({"query": args.target, "results": hits}, indent=2, ensure_ascii=False))
        else:
            for item in hits:
                print(f"• {item.get('name')} ({item.get('package')}): {item.get('summary')}")
        return 0

    if not adb.connect(timeout=15.0):
        print(f"Error: Could not connect to {adb.serial}", file=sys.stderr)
        return 1

    if action == "install":
        info = adb.install_apk(
            args.target,
            grant_permissions=not args.no_grant,
            clear_data=bool(args.clear),
            expected_sha256=getattr(args, "sha256", None),
        )
        launched = None
        if args.launch and info.package:
            launched = adb.launch_app(info.package)
        payload = {"ok": True, "installed": info.to_dict(), "launched": launched}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"✅ Installed {info.package or info.source} "
                f"(granted {info.permissions_granted} permissions, {info.appops_granted} appops)"
            )
        return 0

    if action == "grant":
        perms, ops = adb.grant_all_permissions(args.target)
        payload = {"ok": True, "package": args.target, "permissions": perms, "appops": ops}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"✅ Granted {perms} runtime permissions and {ops} appops to {args.target}")
        return 0

    if action == "launch":
        res = adb.launch_app(args.target)
        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(f"🚀 Launched {res.get('component') or args.target}")
        return 0 if res.get("launched") else 1

    if action == "stop":
        adb.stop_app(args.target)
        if args.json:
            print(json.dumps({"ok": True, "stopped": args.target}))
        else:
            print(f"⏹ Stopped {args.target}")
        return 0

    if action == "clear":
        ok = adb.clear_app_data(args.target)
        if not args.no_grant:
            adb.grant_all_permissions(args.target)
        if args.json:
            print(json.dumps({"ok": ok, "cleared": args.target}))
        else:
            print(f"🧹 Cleared data for {args.target} (ok={ok})")
        return 0 if ok else 1

    if action == "list":
        launcher_apps = adb.list_launcher_apps()
        third_party = adb.list_third_party_packages()
        apps = [a for a in launcher_apps if a["package"] in third_party] or launcher_apps
        if args.json:
            print(json.dumps({"packages": apps}, indent=2))
        else:
            for item in apps:
                print(f"• {item['package']} -> {item['component']}")
        return 0

    return 1


def cmd_device(args: argparse.Namespace) -> int:
    safe_mode, shell_allowlist = _resolve_safe_args(args)
    adb = AdbDevice(
        serial=args.serial,
        safe_mode=True if safe_mode else None,
        shell_allowlist=shell_allowlist if shell_allowlist else None,
    )
    if not adb.connect(timeout=15.0):
        print(f"Error: Could not connect to {adb.serial}", file=sys.stderr)
        return 1

    act = args.device_action
    if act == "push":
        res = adb.push_file(args.src, args.dest)
        print(json.dumps(res, indent=2) if args.json else f"📤 {res['local']} -> {res['remote']}")
        return 0

    if act == "pull":
        res = adb.pull_file(args.src, args.dest)
        print(json.dumps(res, indent=2) if args.json else f"📥 {res['remote']} -> {res['local']}")
        return 0

    if act == "open":
        res = adb.open_url(args.uri, package=args.package)
        print(json.dumps(res, indent=2) if args.json else f"🌐 Opened {args.uri}")
        return 0 if res.get("opened") else 1

    if act == "clipboard":
        if args.text is not None:
            helper = AccessibilityHelperClient(adb)
            helper.action("clipboard", text=args.text)
            adb.set_clipboard(args.text)
            print(json.dumps({"ok": True, "clipboard": args.text}) if args.json else "✅ Clipboard updated")
        else:
            val = adb.get_clipboard()
            print(json.dumps({"clipboard": val}) if args.json else val)
        return 0

    if act == "notifications":
        notifs = adb.get_notifications(include_system=bool(args.all))
        if args.json:
            print(json.dumps({"notifications": notifs}, indent=2, ensure_ascii=False))
        else:
            for n in notifs:
                print(f"[{n.get('package')}] {n.get('title')}: {n.get('text')}")
        return 0

    if act == "shell":
        try:
            out = adb.user_shell(args.command)
        except PermissionError as exc:
            if args.json:
                print(json.dumps({"ok": False, "command": args.command, "error": str(exc)}, indent=2))
            else:
                print(f"Error: {exc}", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps({"command": args.command, "output": out}, indent=2))
        else:
            print(out)
        return 0

    if act == "clean":
        stopped = adb.trim_background_apps()
        if args.json:
            print(json.dumps({"ok": True, "stopped_packages": stopped}, indent=2))
        else:
            print(f"🧹 Cleaned {len(stopped)} background app(s): {', '.join(stopped) if stopped else 'none'}")
            print("⚡ Reclaimed kernel memory caches (drop_caches).")
        return 0

    return 1


def cmd_ui(args: argparse.Namespace) -> int:
    from agentdroid.engine import AndroidEngine

    adb = AdbDevice(serial=args.serial)
    if not adb.connect(timeout=15.0):
        print(f"Error: Could not connect to {adb.serial}", file=sys.stderr)
        return 1
    engine = AndroidEngine(adb)
    act = args.ui_action

    if act == "dump":
        summary = engine.get_screen_data(
            max_elements=args.max_elements,
            include_ime=bool(getattr(args, "include_ime", False)),
        )
        if args.json:
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            fg = summary.get("foreground", {}).get("component") or "unknown"
            print(f"Foreground: {fg} | Elements: {summary.get('element_count')}")
            print(summary.get("formatted_text", ""))
        return 0

    if act == "tap":
        res = engine.tap(float(args.x), float(args.y))
        if args.json:
            print(json.dumps(res))
        return 0 if res.get("success") else 1

    if act == "type":
        res = engine.helper.action("type", text=args.text, append=bool(args.append))
        if args.json:
            print(json.dumps(res))
        return 0 if res.get("success") else 1

    if act == "swipe":
        res = engine.swipe(
            float(args.x1),
            float(args.y1),
            float(args.x2),
            float(args.y2),
            duration_ms=int(args.duration),
        )
        if args.json:
            print(json.dumps(res))
        return 0 if res.get("success") else 1

    if act == "key":
        res = engine.helper.action("global", action=args.keycode)
        if args.json:
            print(json.dumps(res))
        return 0 if res.get("success") else 1

    if act == "screenshot":
        saved = adb.screenshot(args.output)
        if args.json:
            print(json.dumps({"ok": True, "screenshot": saved}))
        else:
            print(saved)
        return 0

    return 1


def cmd_pipeline(args: argparse.Namespace) -> int:
    spec = PipelineSpec.from_file(args.file)
    if args.serial:
        spec.serial = args.serial
    if args.watch:
        spec.watch = True
        spec.headless = False
    elif args.headless:
        spec.headless = True
        spec.watch = False

    safe_mode, shell_allowlist = _resolve_safe_args(args)
    if safe_mode:
        spec.safe_mode = True
    if shell_allowlist:
        spec.shell_allowlist = shell_allowlist

    report: dict[str, Any] | None = None
    if spec.headless and os.environ.get("AGENTDROID_NO_DAEMON") != "1":
        from agentdroid.daemon import run_via_daemon

        report = run_via_daemon(spec)
    if report is None:
        pipeline = CompoundPipeline(spec)
        report = pipeline.run()
    _print_output(report, as_json=bool(args.json))
    return 0 if report.get("ok") else 1


def _run_doctor_checks(serial: str | None = None) -> dict[str, Any]:
    adb = AdbDevice(serial=serial)
    connected = adb.connect(timeout=5.0)
    is_root = adb.ensure_root() if connected else False
    silent_ok = adb.is_provisioned_silent() if connected else False

    helper = AccessibilityHelperClient(adb)
    helper_ping = helper.ping() if connected else None
    input_daemon_ok = helper._input_daemon_ping() if connected else False
    helper.close()

    helper_integrity = verify_bundled_helper_apk(REPO_ROOT, strict=False)

    touchscreen_source = False
    if connected:
        try:
            devs = adb.shell("dumpsys input | grep -E 'Device -?[0-9]+:|Sources:'", timeout=5.0)
            touchscreen_source = "0x00001002" in devs
        except (OSError, RuntimeError) as exc:
            logger.debug("Touchscreen probe failed: %s", exc)
            touchscreen_source = False

    binder_ok = False
    try:
        filesystems = Path("/proc/filesystems").read_text(encoding="utf-8")
        binder_ok = "binder" in filesystems
    except OSError:
        pass

    uinput_ok = False
    try:
        misc_devs = Path("/proc/misc").read_text(encoding="utf-8")
        uinput_ok = any(line.strip().endswith("uinput") for line in misc_devs.splitlines())
    except OSError:
        pass

    return {
        "ok": bool(connected and silent_ok and helper_ping is not None and helper_integrity["ok"]),
        "host": {
            "adb_installed": bool(shutil.which("adb")),
            "scrcpy_installed": bool(shutil.which("scrcpy")),
            "docker_installed": bool(shutil.which("docker")),
            "kernel_binder_loaded": binder_ok,
            "kernel_uinput_loaded": uinput_ok,
        },
        "device": {
            "serial": adb.serial,
            "connected": connected,
            "root_adb": is_root,
            "silent_provisioned": silent_ok,
            "touchscreen_source": touchscreen_source,
            "foreground": adb.foreground_app() if connected else None,
        },
        "accessibility_helper": helper_ping or {"reachable": False},
        "helper_apk_integrity": helper_integrity,
        "input_daemon": {"reachable": bool(input_daemon_ok), "port": INPUT_DAEMON_PORT},
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    report = _run_doctor_checks(serial=args.serial)
    adb = AdbDevice(serial=args.serial)
    helper_ping = report.get("accessibility_helper") or {}
    helper_integrity = report.get("helper_apk_integrity") or {}
    input_daemon = report.get("input_daemon") or {}

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"AgentDroid Doctor ({adb.serial})")
        print(
            f"  • Host Tools:         adb={report['host']['adb_installed']}, "
            f"scrcpy={report['host']['scrcpy_installed']}, "
            f"binder={report['host']['kernel_binder_loaded']}, "
            f"uinput={report['host']['kernel_uinput_loaded']}"
        )
        print(
            f"  • Device Connected:   {report['device']['connected']} "
            f"(root={report['device']['root_adb']}, silent_provisioned={report['device']['silent_provisioned']}, "
            f"touchscreen={report['device']['touchscreen_source']})"
        )
        is_reachable = bool(helper_ping.get("reachable") or helper_ping.get("success"))
        print(
            f"  • Accessibility Helper: "
            f"{'reachable (v' + str(helper_ping.get('version_name')) + ')' if is_reachable else 'not reachable'}"
        )
        print(
            f"  • Bundled Helper APK:   "
            f"{'SHA-256 verified' if helper_integrity.get('ok') else 'FAILED (' + str(helper_integrity.get('error')) + ')'}"
        )
        port = input_daemon.get("port", INPUT_DAEMON_PORT)
        print(
            f"  • Input Daemon ({port}): "
            f"{'reachable' if input_daemon.get('reachable') else 'not reachable'}"
        )
    return 0 if report["ok"] else 1


def cmd_setup(args: argparse.Namespace) -> int:
    if getattr(args, "agents_only", False):
        mounted = install_agent_skills_and_rules()
        if args.json:
            print(json.dumps({"ok": True, **mounted}, indent=2))
        else:
            print("✅ Mounted AgentDroid skills & rules into your AI coding assistants:")
            for p in mounted["skills_installed"] + mounted["rules_installed"]:
                print(f"  • {p}")
        return 0

    configure_agents = not bool(getattr(args, "no_agents", False))
    res = run_one_command_setup(
        start_stack=not args.no_start,
        build_images=bool(args.build),
        watch=bool(args.watch),
        configure_agents=configure_agents,
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"✅ Global CLI installed at: {res['cli_binary']}")
        if configure_agents:
            skills_cnt = len(res["ai_agents_configured"]["skills_installed"])
            rules_cnt = len(res["ai_agents_configured"]["rules_installed"])
            print(f"✅ AI Agents configured:    {skills_cnt} skill locations, {rules_cnt} global rule files")
        else:
            print("ℹ AI agent config injection skipped (--no-agents). Run 'agentdroid setup --agents-only' to opt in.")
        st = res.get("stack", {})
        if st.get("started"):
            print("✅ Silent Android device is up and provisioned!")
        elif st.get("skipped"):
            print("ℹ Stack startup skipped (--no-start). Run 'agentdroid up' when ready.")
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from agentdroid.mcp import McpServer, install_mcp_config

    if getattr(args, "install", False):
        res = install_mcp_config(getattr(args, "target", "all"))
        if getattr(args, "json", False):
            print(json.dumps({"ok": True, **res}, indent=2))
        else:
            print("✅ Installed AgentDroid MCP Server into AI agent configurations:")
            for p in res.get("installed", []):
                print(f"  • {p}")
        return 0

    safe_mode, shell_allowlist = _resolve_safe_args(args)
    server = McpServer(
        serial=getattr(args, "serial", None),
        safe_mode=True if safe_mode else None,
        shell_allowlist=shell_allowlist if shell_allowlist else None,
    )
    server.run_stdio()
    return 0


def cmd_daemon(args: argparse.Namespace) -> int:
    from agentdroid.daemon import daemon_status, serve_daemon, start_daemon, stop_daemon

    action = str(getattr(args, "action", "status"))
    if action == "serve":
        return serve_daemon()
    if action == "start":
        res = start_daemon()
    elif action == "stop":
        res = stop_daemon()
    else:
        res = daemon_status()

    if getattr(args, "json", False):
        print(json.dumps(res, indent=2))
    else:
        print(json.dumps(res))
    return 0
