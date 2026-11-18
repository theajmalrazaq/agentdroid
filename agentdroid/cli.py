"""Command-line interface for AgentDroid (agentdroid) — General-purpose AI Android environment."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Any

from agentdroid.adb import AdbDevice
from agentdroid.helper import INPUT_DAEMON_PORT, AccessibilityHelperClient
from agentdroid.installer import install_agent_skills_and_rules, run_one_command_setup
from agentdroid.pipeline import CompoundPipeline, PipelineSpec, parse_do_step
from agentdroid.watcher import LiveWatcher

REPO_ROOT = Path(__file__).resolve().parent.parent

KNOWN_SUBCOMMANDS = {
    "setup",
    "init",
    "run",
    "watch",
    "up",
    "down",
    "provision",
    "app",
    "device",
    "ui",
    "pipeline",
    "doctor",
    "mcp",
    "daemon",
    "ai",
    "-h",
    "--help",
    "--version",
}


def _print_output(data: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    ok = data.get("ok", True)
    status_icon = "✅" if ok else "✖"
    mode = data.get("mode", "headless")
    device = data.get("device", "")
    dur = data.get("duration_sec", 0.0)
    print(f"{status_icon} AgentDroid [{mode}] on {device} ({dur}s)")

    for pf in data.get("pushed_files") or []:
        print(f"  📤 Pushed:    {pf.get('local')} -> {pf.get('remote')}")

    for apk in data.get("installed_apks") or []:
        print(
            f"  📦 Installed: {apk.get('package') or apk.get('source')} "
            f"(permissions granted: {apk.get('permissions_granted')}, appops: {apk.get('appops_granted')})"
        )

    launched = data.get("launched_app")
    if isinstance(launched, dict) and launched.get("package"):
        print(f"  🚀 Launched:  {launched.get('component') or launched.get('package')}")

    for u in data.get("opened_urls") or []:
        print(f"  🌐 Opened:    {u.get('uri')}")

    for plf in data.get("pulled_files") or []:
        print(f"  📥 Pulled:    {plf.get('remote')} -> {plf.get('local')}")

    if data.get("clipboard") is not None:
        print(f"  📎 Clipboard: {data['clipboard']}")

    if data.get("notifications") is not None:
        notifs = data["notifications"]
        print(f"  🔔 Notifications ({len(notifs)}):")
        for n in notifs[:10]:
            print(f"     [{n.get('package')}] {n.get('title')}: {n.get('text')}")

    crashes = data.get("crashes")
    if isinstance(crashes, dict) and crashes.get("has_crashes"):
        print(
            f"  💥 Crashes detected! fatal={len(crashes.get('fatal_exceptions', []))}, "
            f"anr={len(crashes.get('anrs', []))}"
        )

    if data.get("screenshot"):
        print(f"  📸 Screenshot: {data['screenshot']}")

    ui_sum = data.get("ui_summary")
    if isinstance(ui_sum, dict):
        fg = ui_sum.get("foreground", {}).get("component") or "unknown"
        print(
            f"  🌲 UI Summary ({ui_sum.get('backend')}, fg={fg}): "
            f"{ui_sum.get('element_count')} interactive/labelled elements"
        )
        for el in (ui_sum.get("elements") or [])[:15]:
            print(f"     [{el['id']}] {el['label']} ({el['class']}) @{el['center']}")

    for err in data.get("errors") or []:
        print(f"  ❌ Error: {err}", file=sys.stderr)


class _OrderedUIAction(argparse.Action):
    """Custom argparse Action to preserve the exact interleaving order of UI action flags on the command line."""

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: Any,
        option_string: str | None = None,
    ) -> None:
        if not hasattr(namespace, "ordered_ui_actions"):
            namespace.ordered_ui_actions = []
        namespace.ordered_ui_actions.append((self.dest, values))

        # Maintain standard dest attribute for backwards compatibility
        current = getattr(namespace, self.dest, None) or []
        setattr(namespace, self.dest, current + [values])


def _parse_ui_actions(args: argparse.Namespace) -> list[dict[str, Any]]:
    ordered = getattr(args, "ordered_ui_actions", None)
    if ordered:
        actions: list[dict[str, Any]] = []
        for dest, val in ordered:
            if dest == "do_steps":
                actions.append(parse_do_step(val))
            elif dest == "click_targets":
                actions.append({"type": "click", "selector": val})
            elif dest == "fill_targets":
                if "=" in val:
                    sel, txt = val.split("=", 1)
                    actions.append({"type": "fill", "selector": sel.strip(), "text": txt})
                else:
                    actions.append({"type": "type", "text": val})
            elif dest == "scroll_dirs":
                actions.append({"type": "scroll", "direction": val})
            elif dest == "scroll_to_targets":
                actions.append({"type": "scroll_to", "text": val})
            elif dest == "tap":
                parts = [p.strip() for p in val.split(",")]
                if len(parts) != 2:
                    raise ValueError(f"--tap requires 'x,y' coordinates, got {val!r}")
                actions.append({"type": "tap", "x": float(parts[0]), "y": float(parts[1])})
            elif dest == "type_text":
                actions.append({"type": "type", "text": val})
            elif dest == "swipe":
                parts = [p.strip() for p in val.split(",")]
                if len(parts) not in (4, 5):
                    raise ValueError(f"--swipe requires 'x1,y1,x2,y2[,duration_ms]', got {val!r}")
                actions.append(
                    {
                        "type": "swipe",
                        "x1": float(parts[0]),
                        "y1": float(parts[1]),
                        "x2": float(parts[2]),
                        "y2": float(parts[3]),
                        "duration": int(parts[4]) if len(parts) == 5 else 300,
                    }
                )
            elif dest == "key":
                actions.append({"type": "key", "key": val})
        return actions

    # Fallback if ordered_ui_actions is absent (e.g. manually constructed Namespace in unit tests)
    actions: list[dict[str, Any]] = []
    for raw_do in getattr(args, "do_steps", None) or []:
        actions.append(parse_do_step(raw_do))
    for sel in getattr(args, "click_targets", None) or []:
        actions.append({"type": "click", "selector": sel})
    for fill_spec in getattr(args, "fill_targets", None) or []:
        if "=" in fill_spec:
            sel, txt = fill_spec.split("=", 1)
            actions.append({"type": "fill", "selector": sel.strip(), "text": txt})
        else:
            actions.append({"type": "type", "text": fill_spec})
    for dir_spec in getattr(args, "scroll_dirs", None) or []:
        actions.append({"type": "scroll", "direction": dir_spec})
    for scroll_needle in getattr(args, "scroll_to_targets", None) or []:
        actions.append({"type": "scroll_to", "text": scroll_needle})
    for coord in getattr(args, "tap", None) or []:
        parts = [p.strip() for p in coord.split(",")]
        if len(parts) != 2:
            raise ValueError(f"--tap requires 'x,y' coordinates, got {coord!r}")
        actions.append({"type": "tap", "x": float(parts[0]), "y": float(parts[1])})
    for text in getattr(args, "type_text", None) or []:
        actions.append({"type": "type", "text": text})
    for sw in getattr(args, "swipe", None) or []:
        parts = [p.strip() for p in sw.split(",")]
        if len(parts) not in (4, 5):
            raise ValueError(f"--swipe requires 'x1,y1,x2,y2[,duration_ms]', got {sw!r}")
        actions.append(
            {
                "type": "swipe",
                "x1": float(parts[0]),
                "y1": float(parts[1]),
                "x2": float(parts[2]),
                "y2": float(parts[3]),
                "duration": int(parts[4]) if len(parts) == 5 else 300,
            }
        )
    for k in getattr(args, "key", None) or []:
        actions.append({"type": "key", "key": k})
    return actions


def cmd_run(args: argparse.Namespace) -> int:
    clear_pkgs = list(args.clear_data or [])
    if args.clear_installed:
        clear_pkgs.append("auto")

    launch_target = args.launch
    if args.launch_installed and not launch_target:
        launch_target = "auto"

    watch_mode = bool(args.watch)
    headless_mode = not watch_mode

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
    env.setdefault("AGENTDROID_API_KEY", "local-dev-key")
    if args.image:
        env["REDROID_IMAGE"] = args.image

    cmd = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
    if args.build:
        cmd.append("--build")
    if not args.with_server:
        # Local use: only the Android device. The cloud server needs AGENTDROID_API_KEY.
        cmd.append("redroid")

    if not args.json:
        print("[agentdroid:up] Starting AgentDroid Docker Compose stack...", file=sys.stderr)
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
    adb = AdbDevice(serial=args.serial)
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
        pkgs = sorted(adb.list_third_party_packages())
        if args.json:
            print(json.dumps({"packages": pkgs}, indent=2))
        else:
            for p in pkgs:
                print(p)
        return 0

    return 1


def cmd_device(args: argparse.Namespace) -> int:
    adb = AdbDevice(serial=args.serial)
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
        out = adb.shell(args.command)
        if args.json:
            print(json.dumps({"command": args.command, "output": out}, indent=2))
        else:
            print(out)
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
    report: dict[str, Any] | None = None
    if headless_mode and os.environ.get("AGENTDROID_NO_DAEMON") != "1":
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

    touchscreen_source = False
    if connected:
        try:
            devs = adb.shell("dumpsys input | grep -E 'Device -?[0-9]+:|Sources:'", timeout=5.0)
            touchscreen_source = "0x00001002" in devs
        except Exception:
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
        "ok": bool(connected and silent_ok and helper_ping is not None),
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
        "input_daemon": {"reachable": bool(input_daemon_ok), "port": INPUT_DAEMON_PORT},
    }


def cmd_doctor(args: argparse.Namespace) -> int:
    report = _run_doctor_checks(serial=args.serial)
    adb = AdbDevice(serial=args.serial)
    helper_ping = report.get("accessibility_helper") or {}
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
        print(f"  • Accessibility Helper: {'reachable (v' + str(helper_ping.get('version_name')) + ')' if is_reachable else 'not reachable'}")
        port = input_daemon.get("port", INPUT_DAEMON_PORT)
        print(f"  • Input Daemon ({port}): {'reachable' if input_daemon.get('reachable') else 'not reachable'}")
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

    res = run_one_command_setup(
        start_stack=not args.no_start,
        build_images=bool(args.build),
        watch=bool(args.watch),
    )
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"✅ Global CLI installed at: {res['cli_binary']}")
        skills_cnt = len(res["ai_agents_configured"]["skills_installed"])
        rules_cnt = len(res["ai_agents_configured"]["rules_installed"])
        print(f"✅ AI Agents configured:    {skills_cnt} skill locations, {rules_cnt} global rule files")
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

    server = McpServer(serial=getattr(args, "serial", None))
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


def cmd_ai(args: argparse.Namespace) -> int:
    """Run autonomous decision-making powered directly by TypeSafe AI (Jev System One)."""
    from agentdroid.engine import AndroidEngine
    from agentdroid.typesafe_ai import TypeSafeAIClient

    adb = AdbDevice(serial=args.serial)
    if not adb.connect(timeout=15.0):
        print(f"Error: Could not connect to {adb.serial}", file=sys.stderr)
        return 1

    watcher = None
    if getattr(args, "watch", False):
        watcher = LiveWatcher(
            adb.serial,
            watch=True,
            interactive_control=bool(getattr(args, "interactive", False)),
            always_on_top=not getattr(args, "no_always_on_top", False),
            window_width=getattr(args, "window_width", 412),
            window_height=getattr(args, "window_height", 892),
            borderless=bool(getattr(args, "borderless", False)),
        )
        info = watcher.start()
        print(
            f"[agentdroid:ai] Live watcher attached ({info.get('viewer')})",
            file=sys.stderr,
        )

    try:
        if getattr(args, "clear_data", None):
            for pkg in args.clear_data:
                adb.clear_package_data(pkg)
        if getattr(args, "launch", None):
            adb.launch_app(args.launch, wait=True)
            time.sleep(1.0)

        engine = AndroidEngine(adb)
        api_key = (
            getattr(args, "key", None)
            or os.environ.get("TYPESAFE_API_KEY")
            or ""
        )
        client = TypeSafeAIClient(api_key=api_key)
        goal = args.prompt
        max_steps = getattr(args, "max_steps", 10)
        model = getattr(args, "model", "jev-latest")

        print(f"[agentdroid:ai] Goal: '{goal}' | Model: {model} | Device: {adb.serial}")

        history: list[dict[str, Any]] = []
        is_success = False

        for step in range(1, max_steps + 1):
            ui = engine.get_screen_data(max_elements=80)
            decision = client.rank_next_action(ui, goal, model=model)
            action_key = decision.get("action_key", "wait")
            conf = decision.get("confidence", 0.0)
            latency = decision.get("latency_ms", 0.0)
            matched = decision.get("matched_element")
            is_goal_met = decision.get("is_goal_met", False)

            step_record = {
                "step": step,
                "action": action_key,
                "confidence": conf,
                "latency_ms": latency,
                "goal_met": is_goal_met,
            }
            history.append(step_record)

            label = matched.get("label") or matched.get("desc") if matched else ""
            print(
                f"[agentdroid:ai] Step {step}/{max_steps}: {action_key} "
                f"({label or 'none'}) [conf={conf:.2f}, {latency}ms]"
            )

            if is_goal_met and action_key == "wait":
                print(f"✅ [agentdroid:ai] Goal satisfied! '{goal}'")
                is_success = True
                break

            if action_key.startswith("tap_") and matched:
                center = matched.get("center") or (540, 1200)
                engine.tap(float(center[0]), float(center[1]))
                time.sleep(0.6)
            elif action_key == "back":
                engine.helper.action("global", action="BACK")
                time.sleep(0.6)
            elif action_key == "wait":
                time.sleep(1.0)
            else:
                time.sleep(0.5)

            if is_goal_met:
                print(f"✅ [agentdroid:ai] Goal satisfied! '{goal}'")
                is_success = True
                break

        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": is_success,
                        "goal": goal,
                        "model": model,
                        "steps": len(history),
                        "history": history,
                    },
                    indent=2,
                )
            )

        return 0 if is_success or len(history) > 0 else 1
    finally:
        if watcher is not None:
            time.sleep(0.5)
            watcher.stop(force=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agentdroid",
        description=(
            "AgentDroid: Silent General-Purpose Android Environment for AI Agents (Redroid).\n"
            "Allows AI agents to use Android for any task — installing tools/apps on demand, opening URLs/deep links,\n"
            "pushing/pulling files, reading notifications/clipboard, and executing multi-step UI workflows in one call\n"
            "with silent --headless background mode and live --watch visual mode."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--version", action="version", version="agentdroid 0.3.0")
    subparsers = parser.add_subparsers(dest="subcommand")

    # --- setup / init ---
    for setup_name in ("setup", "init"):
        setup_p = subparsers.add_parser(
            setup_name,
            help="One-command setup: install global CLI, configure API key, mount skills/rules into all AI agents, and boot the silent Android device.",
        )
        setup_p.add_argument("--no-start", action="store_true", help="Configure CLI and AI agent rules without starting Docker containers.")
        setup_p.add_argument("--agents-only", action="store_true", help="Only install/update AI agent skills & rules.")
        setup_p.add_argument("--build", action="store_true", help="Build Docker images when starting stack.")
        setup_p.add_argument("-w", "--watch", action="store_true", help="Open live viewer after starting stack.")
        setup_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
        setup_p.set_defaults(func=cmd_setup)

    # --- run ---
    run_p = subparsers.add_parser(
        "run",
        help="Execute a compound multi-step Android workflow (install apps, push/pull files, open URLs, read notifications/output) in one call.",
    )
    _add_run_arguments(run_p)

    # --- watch ---
    watch_p = subparsers.add_parser(
        "watch",
        help="Watch live what the AI agent is doing (opens scrcpy/web stream with --watch, or streams background JSONL with --headless).",
    )
    watch_p.add_argument("-s", "--serial", help="Target Android device serial (default: 127.0.0.1:5555).")
    watch_p.add_argument(
        "--headless",
        action="store_true",
        help="Stream agent events & foreground changes in background as JSONL without opening any GUI window.",
    )
    watch_p.add_argument(
        "-w",
        "--watch",
        action="store_true",
        default=True,
        help="Open live visual viewer (scrcpy or web stream) + terminal action telemetry (default).",
    )
    watch_p.add_argument(
        "--interactive",
        action="store_true",
        help="Allow mouse/keyboard input inside the scrcpy watch window.",
    )
    watch_p.add_argument(
        "--window-width",
        type=int,
        default=412,
        help="Width of the floating simulator watch window in pixels (default: 412).",
    )
    watch_p.add_argument(
        "--window-height",
        type=int,
        default=892,
        help="Height of the floating simulator watch window in pixels (default: 892).",
    )
    watch_p.add_argument(
        "--no-always-on-top",
        action="store_true",
        help="Do not keep the simulator watch window floating on top.",
    )
    watch_p.add_argument(
        "--borderless",
        action="store_true",
        help="Display the mobile simulator window borderless.",
    )
    watch_p.set_defaults(func=cmd_watch)

    # --- up ---
    up_p = subparsers.add_parser(
        "up",
        help="Start the headless Redroid + server Docker Compose stack and silently provision the device.",
    )
    up_p.add_argument("-s", "--serial", help="ADB serial (default: 127.0.0.1:5555).")
    up_p.add_argument("--image", help="Override Redroid Docker image tag.")
    up_p.add_argument("--build", action="store_true", help="Rebuild Docker images before starting.")
    up_p.add_argument("--with-server", action="store_true", help="Also start the central cloud server (requires AGENTDROID_API_KEY).")
    up_p.add_argument("--headless", action="store_true", default=True, help="Run silently in background (default).")
    up_p.add_argument("-w", "--watch", action="store_true", help="Open live scrcpy viewer once booted.")
    up_p.add_argument("--window-width", type=int, default=412, help="Width of the simulator watch window.")
    up_p.add_argument("--window-height", type=int, default=892, help="Height of the simulator watch window.")
    up_p.add_argument("--no-always-on-top", action="store_true", help="Do not keep simulator window on top.")
    up_p.add_argument("--borderless", action="store_true", help="Display simulator window borderless.")
    up_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    up_p.set_defaults(func=cmd_up)

    # --- down ---
    down_p = subparsers.add_parser("down", help="Stop the Redroid + server Docker Compose stack.")
    down_p.add_argument("-v", "--volumes", action="store_true", help="Also remove persistent data volumes.")
    down_p.set_defaults(func=cmd_down)

    # --- provision ---
    prov_p = subparsers.add_parser(
        "provision",
        help="Configure an Android/Redroid device for silent AI agent usage (root ADB, animations=0, audio muted, accessibility helper enabled).",
    )
    prov_p.add_argument("-s", "--serial", help="Target Android device serial.")
    prov_p.add_argument("--force", action="store_true", help="Re-apply all settings even if already provisioned.")
    prov_p.add_argument("-j", "--json", action="store_true", help="Print JSON result.")
    prov_p.set_defaults(func=cmd_provision)

    # --- app ---
    app_p = subparsers.add_parser(
        "app",
        help="Search F-Droid, install APKs (from file, URL, or F-Droid), auto-grant permissions, and manage apps.",
    )
    app_p.add_argument(
        "app_action",
        choices=["search", "install", "grant", "launch", "stop", "clear", "list"],
    )
    app_p.add_argument(
        "target",
        nargs="?",
        default="",
        help="Search query, APK path, HTTP URL, 'fdroid:<query>', or Android package name.",
    )
    app_p.add_argument("-s", "--serial", help="Target Android device serial.")
    app_p.add_argument("--launch", action="store_true", help="Launch app immediately after install.")
    app_p.add_argument("--clear", action="store_true", help="Clear app data on install.")
    app_p.add_argument("--no-grant", action="store_true", help="Skip auto-granting runtime permissions.")
    app_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    app_p.set_defaults(func=cmd_app)

    # --- device ---
    dev_p = subparsers.add_parser(
        "device",
        help="General-purpose device operations: push/pull files, open URLs/deep links, clipboard, notifications, root shell.",
    )
    dev_sub = dev_p.add_subparsers(dest="device_action", required=True)

    push_p = dev_sub.add_parser("push", help="Push local file/folder onto the Android device.")
    push_p.add_argument("src", help="Local path.")
    push_p.add_argument("dest", nargs="?", default="/sdcard/Download/", help="Remote path (default: /sdcard/Download/).")
    push_p.add_argument("-s", "--serial")
    push_p.add_argument("-j", "--json", action="store_true")

    pull_p = dev_sub.add_parser("pull", help="Pull remote file/folder from the Android device to workspace.")
    pull_p.add_argument("src", help="Remote path on Android.")
    pull_p.add_argument("dest", nargs="?", default="./artifacts/", help="Local destination (default: ./artifacts/).")
    pull_p.add_argument("-s", "--serial")
    pull_p.add_argument("-j", "--json", action="store_true")

    open_p = dev_sub.add_parser("open", help="Open a web URL or deep link URI on the device.")
    open_p.add_argument("uri", help="URL or URI (e.g. https://example.com, tg://..., geo:...).")
    open_p.add_argument("-p", "--package", help="Optional package to handle the URI.")
    open_p.add_argument("-s", "--serial")
    open_p.add_argument("-j", "--json", action="store_true")

    clip_p = dev_sub.add_parser("clipboard", help="Get or set the Android device clipboard.")
    clip_p.add_argument("text", nargs="?", default=None, help="Text to set on clipboard (omit to read clipboard).")
    clip_p.add_argument("-s", "--serial")
    clip_p.add_argument("-j", "--json", action="store_true")

    notif_p = dev_sub.add_parser("notifications", help="Read active device notifications (OTP codes, messages, etc.).")
    notif_p.add_argument("--all", action="store_true", help="Include system notifications.")
    notif_p.add_argument("-s", "--serial")
    notif_p.add_argument("-j", "--json", action="store_true")

    sh_p = dev_sub.add_parser("shell", help="Execute a root ADB shell command on the device.")
    sh_p.add_argument("command", help="Shell command string.")
    sh_p.add_argument("-s", "--serial")
    sh_p.add_argument("-j", "--json", action="store_true")

    dev_p.set_defaults(func=cmd_device)

    # --- ui ---
    ui_p = subparsers.add_parser(
        "ui",
        help="Direct sub-second UI hierarchy dump & gestures via the on-device accessibility helper.",
    )
    ui_sub = ui_p.add_subparsers(dest="ui_action", required=True)

    dump_p = ui_sub.add_parser("dump", help="Dump compact, token-efficient visible UI elements.")
    dump_p.add_argument("-s", "--serial", help="Target device serial.")
    dump_p.add_argument("--max-elements", type=int, default=60)
    dump_p.add_argument("--include-ime", action="store_true", help="Include soft-keyboard keys in UI dump.")
    dump_p.add_argument("-j", "--json", action="store_true")

    tap_p = ui_sub.add_parser("tap", help="Tap screen coordinates.")
    tap_p.add_argument("x", type=float)
    tap_p.add_argument("y", type=float)
    tap_p.add_argument("-s", "--serial")
    tap_p.add_argument("-j", "--json", action="store_true")

    type_p = ui_sub.add_parser("type", help="Input text into focused field.")
    type_p.add_argument("text")
    type_p.add_argument("--append", action="store_true")
    type_p.add_argument("-s", "--serial")
    type_p.add_argument("-j", "--json", action="store_true")

    swipe_p = ui_sub.add_parser("swipe", help="Swipe from (x1,y1) to (x2,y2).")
    swipe_p.add_argument("x1", type=float)
    swipe_p.add_argument("y1", type=float)
    swipe_p.add_argument("x2", type=float)
    swipe_p.add_argument("y2", type=float)
    swipe_p.add_argument("duration", nargs="?", type=int, default=300)
    swipe_p.add_argument("-s", "--serial")
    swipe_p.add_argument("-j", "--json", action="store_true")

    key_p = ui_sub.add_parser("key", help="Send global action / key (HOME, BACK, RECENTS, ENTER).")
    key_p.add_argument("keycode")
    key_p.add_argument("-s", "--serial")
    key_p.add_argument("-j", "--json", action="store_true")

    shot_p = ui_sub.add_parser("screenshot", help="Save PNG screenshot.")
    shot_p.add_argument("output")
    shot_p.add_argument("-s", "--serial")
    shot_p.add_argument("-j", "--json", action="store_true")

    ui_p.set_defaults(func=cmd_ui)

    # --- pipeline ---
    pipe_p = subparsers.add_parser("pipeline", help="Run a multi-step JSON workflow specification in one call.")
    pipe_p.add_argument("file", help="Path to JSON pipeline file.")
    pipe_p.add_argument("-s", "--serial", help="Override target device serial.")
    pipe_p.add_argument("--headless", action="store_true", help="Force silent background mode.")
    pipe_p.add_argument("-w", "--watch", action="store_true", help="Force live visual watch mode.")
    pipe_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    pipe_p.set_defaults(func=cmd_pipeline)

    # --- doctor ---
    doc_p = subparsers.add_parser("doctor", help="Check Redroid, ADB root, silent settings, and helper health.")
    doc_p.add_argument("-s", "--serial", help="Target Android device serial.")
    doc_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    doc_p.set_defaults(func=cmd_doctor)

    # --- mcp ---
    mcp_p = subparsers.add_parser(
        "mcp",
        help="Run or install Model Context Protocol (MCP) server for Claude Code, Codex, Antigravity, and Cursor.",
    )
    mcp_p.add_argument("-s", "--serial", help="Target device serial.")
    mcp_p.add_argument(
        "--install",
        action="store_true",
        help="Configure MCP in Claude Code, Codex, Antigravity, and Cursor config files.",
    )
    mcp_p.add_argument(
        "--target",
        choices=["all", "claude", "codex", "antigravity", "cursor"],
        default="all",
        help="Target AI assistant to configure (default: all).",
    )
    mcp_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    mcp_p.set_defaults(func=cmd_mcp)

    # --- daemon ---
    daemon_p = subparsers.add_parser(
        "daemon",
        help="Manage the persistent warm local Unix-socket daemon (eliminates CLI startup overhead).",
    )
    daemon_p.add_argument(
        "action",
        choices=["start", "stop", "status", "serve"],
        help="Daemon lifecycle action.",
    )
    daemon_p.add_argument("-j", "--json", action="store_true", help="Print JSON output.")
    daemon_p.set_defaults(func=cmd_daemon)

    # --- ai ---
    ai_p = subparsers.add_parser(
        "ai",
        help="Run autonomous sub-second goal execution powered directly by TypeSafe AI (Jev System One).",
    )
    ai_p.add_argument(
        "prompt",
        help="Natural language goal or task prompt (e.g. 'Start the stopwatch' or 'Navigate to Timer').",
    )
    ai_p.add_argument("-s", "--serial", help="Target Android device serial (default: 127.0.0.1:5555).")
    ai_p.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Launch live visual viewer (scrcpy) during autonomous execution.",
    )
    ai_p.add_argument(
        "--interactive",
        action="store_true",
        help="Allow mouse/keyboard input inside watch window.",
    )
    ai_p.add_argument(
        "--window-width",
        type=int,
        default=412,
        help="Width of the floating watch window in pixels (default: 412).",
    )
    ai_p.add_argument(
        "--window-height",
        type=int,
        default=892,
        help="Height of the floating watch window in pixels (default: 892).",
    )
    ai_p.add_argument(
        "--no-always-on-top",
        action="store_true",
        help="Do not keep the watch window on top.",
    )
    ai_p.add_argument(
        "--borderless",
        action="store_true",
        help="Run watch window without window decorations/borders.",
    )
    ai_p.add_argument(
        "--max-steps",
        type=int,
        default=10,
        help="Maximum autonomous decision steps (default: 10).",
    )
    ai_p.add_argument(
        "--launch",
        metavar="PACKAGE",
        help="Launch this Android package or component before starting the decision loop.",
    )
    ai_p.add_argument(
        "--clear-data",
        action="append",
        metavar="PACKAGE",
        help="Clear package user data before starting (repeatable).",
    )
    ai_p.add_argument(
        "--key",
        help="TypeSafe AI API key (defaults to TYPESAFE_API_KEY env var).",
    )
    ai_p.add_argument(
        "--model",
        default="jev-latest",
        help="TypeSafe model identifier (default: jev-latest).",
    )
    ai_p.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit JSON execution report.",
    )
    ai_p.set_defaults(func=cmd_ai)

    return parser


def _add_run_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("-s", "--serial", help="Target Android device serial (default: 127.0.0.1:5555).")
    p.add_argument(
        "--headless",
        action="store_true",
        default=True,
        help="Run silently in background without opening GUI windows (default).",
    )
    p.add_argument(
        "-w",
        "--watch",
        action="store_true",
        help="Show live what the AI agent is doing via a floating mobile simulator overlay window (like macOS iOS Simulator).",
    )
    p.add_argument(
        "--interactive",
        action="store_true",
        help="Allow mouse/keyboard input inside the watch window.",
    )
    p.add_argument(
        "--window-width",
        type=int,
        default=412,
        help="Width of the floating simulator watch window (default: 412, phone simulator).",
    )
    p.add_argument(
        "--window-height",
        type=int,
        default=892,
        help="Height of the floating simulator watch window (default: 892, phone simulator).",
    )
    p.add_argument(
        "--no-always-on-top",
        action="store_true",
        help="Do not keep the simulator watch window floating on top.",
    )
    p.add_argument(
        "--borderless",
        action="store_true",
        help="Display the simulator window borderless.",
    )
    p.add_argument(
        "--no-provision",
        action="store_true",
        help="Skip automatic silent device provisioning check before running.",
    )

    # App installation & permissions (local path, HTTP URL, or fdroid:<query_or_pkg>)
    p.add_argument(
        "-i",
        "--install",
        action="append",
        metavar="SOURCE",
        help="Install app before running: local APK path, HTTP(S) URL, or 'fdroid:<query_or_pkg>' (repeatable; auto-grants permissions).",
    )
    p.add_argument(
        "--no-grant",
        action="store_true",
        help="Do not auto-grant runtime permissions and special appops after installing APKs.",
    )
    p.add_argument(
        "--grant",
        action="append",
        metavar="PACKAGE",
        help="Grant all runtime permissions and special appops to PACKAGE (repeatable).",
    )
    p.add_argument(
        "--clear-data",
        action="append",
        metavar="PACKAGE",
        help="Clear app data for PACKAGE before launching (repeatable).",
    )
    p.add_argument(
        "--clear",
        dest="clear_installed",
        action="store_true",
        help="Clear app data of the installed/target package before launching.",
    )
    p.add_argument(
        "--launch",
        nargs="?",
        const="auto",
        metavar="PACKAGE",
        help="Launch the installed app (or specified PACKAGE/component) before running UI steps.",
    )
    p.add_argument(
        "--launch-installed",
        action="store_true",
        help="Launch the first APK installed via --install.",
    )
    p.add_argument(
        "--stop-after",
        action="store_true",
        help="Force-stop the target package when execution finishes.",
    )

    # General-purpose device I/O (files, URLs, clipboard, notifications)
    p.add_argument(
        "--push",
        action="append",
        metavar="LOCAL[:REMOTE]",
        help="Push file/folder to device before running (default remote: /sdcard/Download/, repeatable).",
    )
    p.add_argument(
        "--pull",
        action="append",
        metavar="REMOTE[:LOCAL]",
        help="Pull file/folder from device after running (default local: ./artifacts/, repeatable).",
    )
    p.add_argument(
        "--open-url",
        action="append",
        metavar="URI",
        help="Open web URL or deep link (https://, tg://, mailto:, geo:, etc.) before UI steps (repeatable).",
    )
    p.add_argument(
        "--set-clipboard",
        metavar="TEXT",
        help="Set Android clipboard text before running.",
    )
    p.add_argument(
        "--get-clipboard",
        action="store_true",
        help="Read and return Android clipboard text after running.",
    )
    p.add_argument(
        "--notifications",
        action="store_true",
        help="Read and return active device notifications (OTP codes, messages, status) in output.",
    )

    # Compound Semantic & Coordinate UI actions (Zero API key needed!)
    p.add_argument(
        "-d",
        "--do",
        dest="do_steps",
        action=_OrderedUIAction,
        metavar="VERB:ARG",
        help="Execute semantic action step in order (e.g. 'click:Login', 'fill:Email=user@test.com', 'scroll-to:Submit', 'key:HOME', 'sleep:1', repeatable).",
    )
    p.add_argument(
        "--click",
        dest="click_targets",
        action=_OrderedUIAction,
        metavar="TEXT_OR_ID",
        help="Click/tap element by text, description, or #index (repeatable).",
    )
    p.add_argument(
        "--fill",
        dest="fill_targets",
        action=_OrderedUIAction,
        metavar="SELECTOR=TEXT",
        help="Fill input field matching SELECTOR with TEXT (repeatable).",
    )
    p.add_argument(
        "--scroll",
        dest="scroll_dirs",
        action=_OrderedUIAction,
        metavar="DIRECTION",
        help="Scroll screen direction: 'down', 'up', 'left', 'right' (repeatable).",
    )
    p.add_argument(
        "--scroll-to",
        dest="scroll_to_targets",
        action=_OrderedUIAction,
        metavar="TEXT",
        help="Scroll down until TEXT is visible on screen (repeatable).",
    )
    p.add_argument(
        "--pre-shell",
        action="append",
        metavar="CMD",
        help="Run root ADB shell command before UI steps (repeatable).",
    )
    p.add_argument(
        "--tap",
        action=_OrderedUIAction,
        metavar="X,Y",
        help="Tap coordinates X,Y (repeatable).",
    )
    p.add_argument(
        "--type",
        dest="type_text",
        action=_OrderedUIAction,
        metavar="TEXT",
        help="Type text into focused field (repeatable).",
    )
    p.add_argument(
        "--swipe",
        action=_OrderedUIAction,
        metavar="X1,Y1,X2,Y2[,MS]",
        help="Swipe coordinates (repeatable).",
    )
    p.add_argument(
        "--key",
        action=_OrderedUIAction,
        metavar="KEY",
        help="Send global key action (HOME, BACK, ENTER, RECENTS, TAB, repeatable).",
    )
    p.add_argument(
        "--wait-text",
        action="append",
        metavar="TEXT",
        help="Wait until TEXT appears on screen before UI steps (repeatable).",
    )
    p.add_argument(
        "--post-shell",
        action="append",
        metavar="CMD",
        help="Run root ADB shell command after UI steps (repeatable).",
    )
    p.add_argument(
        "--assert-text",
        action="append",
        metavar="TEXT",
        help="Verify TEXT is visible on screen after execution (repeatable).",
    )

    p.add_argument(
        "-a",
        "--locked-app",
        metavar="PACKAGE",
        help="Open URLs in this specific Android package.",
    )

    # Diagnostics & outputs
    p.add_argument(
        "--no-check-crashes",
        action="store_true",
        help="Disable automatic logcat crash & ANR inspection.",
    )
    p.add_argument(
        "-l",
        "--collect-logs",
        action="store_true",
        help="Include tail of device logcat in the final output.",
    )
    p.add_argument(
        "--log-lines",
        type=int,
        default=60,
        help="Number of logcat lines to collect when --collect-logs is set (default: 60).",
    )
    p.add_argument(
        "--screenshot",
        metavar="PATH",
        help="Capture final PNG screenshot to PATH.",
    )
    p.add_argument(
        "--dump-ui",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include compact token-efficient UI element hierarchy in output (default: True).",
    )
    p.add_argument(
        "-j",
        "--json",
        action="store_true",
        help="Emit single compact JSON object (ideal for AI coding agents).",
    )
    p.set_defaults(func=cmd_run)


def normalize_argv(argv: list[str]) -> list[str]:
    """Allow `agentdroid --install ... --do "click:Login"` without typing `run` explicitly."""
    if len(argv) > 1 and argv[1] not in KNOWN_SUBCOMMANDS:
        return [argv[0], "run", *argv[1:]]
    return list(argv)


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv if argv is None else [sys.argv[0], *argv]
    norm = normalize_argv(raw_argv)
    parser = build_parser()
    if len(norm) == 1:
        parser.print_help()
        return 0
    args = parser.parse_args(norm[1:])
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    res = func(args)
    return int(res) if res is not None else 0


if __name__ == "__main__":
    raise SystemExit(main())
