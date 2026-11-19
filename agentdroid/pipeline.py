"""Compound single-call execution pipeline for general-purpose AI agent Android tasks.

Designed so the host AI agent on the user's system (Claude Code, Antigravity, Codex,
Cursor, Windsurf) IS the brain and drives the silent Android device directly via the
on-device Artemis Accessibility Helper — requiring ZERO separate .env or API keys.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import sys
import time
from typing import Any

from agentdroid.adb import AdbDevice, InstalledAppInfo
from agentdroid.engine import AndroidEngine, parse_do_step
from agentdroid.watcher import LiveWatcher


@dataclass
class PipelineSpec:
    """Specification for a compound single-call general-purpose Android AI workflow."""

    serial: str | None = None
    headless: bool = True
    watch: bool = False
    auto_provision: bool = True

    # Watcher / Mobile Simulator Overlay styling (iOS Simulator look & feel)
    watch_width: int = 412
    watch_height: int = 892
    always_on_top: bool = True
    watch_borderless: bool = False
    watch_interactive: bool = False

    # App setup & on-demand installation (local APK, URL, or fdroid:<query_or_pkg>)
    install_apks: list[str] = field(default_factory=list)
    grant_all_permissions: bool = True
    grant_packages: list[str] = field(default_factory=list)
    clear_packages: list[str] = field(default_factory=list)
    launch_target: str | None = None  # package, component, or "auto" (launch first installed APK)
    stop_after: bool = False

    # General-purpose device state & I/O (files, URLs, clipboard)
    push_files: list[str] = field(default_factory=list)  # "local_path" or "local_path:remote_path"
    pull_files: list[str] = field(default_factory=list)  # "remote_path" or "remote_path:local_path"
    open_urls: list[str] = field(default_factory=list)   # web URLs or deep links
    set_clipboard: str | None = None
    get_clipboard: bool = False
    read_notifications: bool = False

    # Compound UI & Shell Actions (executed directly via Artemis Accessibility Helper — zero API key!)
    pre_shell: list[str] = field(default_factory=list)
    ui_actions: list[dict[str, Any]] = field(default_factory=list)
    post_shell: list[str] = field(default_factory=list)
    wait_for_text: list[str] = field(default_factory=list)
    assert_texts: list[str] = field(default_factory=list)

    locked_app_package: str | None = None
    safe_mode: bool = False
    shell_allowlist: list[str] = field(default_factory=list)

    # Diagnostics & outputs (dump_ui defaults to True so the host AI agent always gets screen state)
    check_crashes: bool = True
    collect_logs: bool = False
    log_lines: int = 60
    screenshot_path: str | None = None
    dump_ui: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PipelineSpec:
        """Create a PipelineSpec from a JSON-friendly dictionary with convenient API shorthands."""
        data = dict(data)

        if "open_url" in data and "open_urls" not in data:
            val = data.pop("open_url")
            data["open_urls"] = [val] if isinstance(val, str) else list(val)

        if "install" in data and "install_apks" not in data:
            val = data.pop("install")
            data["install_apks"] = [val] if isinstance(val, str) else list(val)

        if "push" in data and "push_files" not in data:
            val = data.pop("push")
            data["push_files"] = [val] if isinstance(val, str) else list(val)

        if "pull" in data and "pull_files" not in data:
            val = data.pop("pull")
            data["pull_files"] = [val] if isinstance(val, str) else list(val)

        if "screenshot" in data and "screenshot_path" not in data:
            data["screenshot_path"] = data.pop("screenshot")

        if "launch" in data and "launch_target" not in data:
            data["launch_target"] = data.pop("launch")

        if "assert_text" in data and "assert_texts" not in data:
            val = data.pop("assert_text")
            data["assert_texts"] = [val] if isinstance(val, str) else list(val)

        if "wait_text" in data and "wait_for_text" not in data:
            val = data.pop("wait_text")
            data["wait_for_text"] = [val] if isinstance(val, str) else list(val)

        if "notifications" in data and "read_notifications" not in data:
            data["read_notifications"] = bool(data.pop("notifications"))

        if "clipboard" in data:
            clip = data.pop("clipboard")
            if isinstance(clip, str):
                data["set_clipboard"] = clip
            elif isinstance(clip, bool):
                data["get_clipboard"] = clip

        if "do" in data:
            do_items = data.pop("do")
            if isinstance(do_items, str):
                do_items = [do_items]
            ui_actions = list(data.get("ui_actions") or [])
            for item in do_items:
                if isinstance(item, str):
                    ui_actions.append(parse_do_step(item))
                elif isinstance(item, dict):
                    ui_actions.append(item)
            data["ui_actions"] = ui_actions

        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)

    @classmethod
    def from_file(cls, path: str | Path) -> PipelineSpec:
        p = Path(path).expanduser().resolve()
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Pipeline file {p} must contain a JSON object")
        return cls.from_dict(data)


class CompoundPipeline:
    """Executes a complete multi-step Android workflow in one call to minimize AI agent token usage."""

    def __init__(self, spec: PipelineSpec) -> None:
        self.spec = spec
        self.adb = AdbDevice(
            serial=spec.serial,
            safe_mode=True if spec.safe_mode else None,
            shell_allowlist=spec.shell_allowlist if spec.shell_allowlist else None,
        )
        self.engine = AndroidEngine(self.adb)
        self.helper = self.engine.helper

    def _log_watch(self, watch_enabled: bool, msg: str) -> None:
        if watch_enabled:
            print(f"[agentdroid:watch] {msg}", file=sys.stderr)

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        spec = self.spec
        watch_enabled = bool(spec.watch and not (spec.headless and not spec.watch))

        watcher = LiveWatcher(
            self.adb.serial,
            watch=watch_enabled,
            interactive_control=spec.watch_interactive,
            always_on_top=spec.always_on_top,
            window_width=spec.watch_width,
            window_height=spec.watch_height,
            borderless=spec.watch_borderless,
        )

        report: dict[str, Any] = {
            "ok": True,
            "mode": "watch" if watch_enabled else "headless",
            "device": self.adb.serial,
            "provision": None,
            "pushed_files": [],
            "installed_apks": [],
            "granted_packages": [],
            "cleared_packages": [],
            "launched_app": None,
            "opened_urls": [],
            "pre_shell_outputs": [],
            "ui_actions_executed": [],
            "captured_vars": {},
            "assertions": [],
            "post_shell_outputs": [],
            "pulled_files": [],
            "clipboard": None,
            "notifications": None,
            "crashes": None,
            "logcat_tail": [],
            "screenshot": None,
            "ui_summary": None,
            "errors": [],
            "duration_sec": 0.0,
        }

        try:
            self.engine.locked_app_package = spec.locked_app_package

            # 1. Connect & silently provision device (/ping fast-path skips ~575ms redundant checks)
            ping_fast_ok = False
            if (
                spec.auto_provision
                and "connect" not in self.adb.__dict__
                and "provision_silent" not in self.adb.__dict__
            ):
                if self.helper.ping() is not None:
                    ping_fast_ok = True
                    report["provision"] = {
                        "provisioned": True,
                        "action": "already_provisioned_fast",
                        "serial": self.adb.serial,
                    }

            if not ping_fast_ok:
                if not self.adb.connect(timeout=25.0):
                    report["ok"] = False
                    report["errors"].append(f"Could not connect to Android device '{self.adb.serial}'")
                    return report

                if spec.auto_provision:
                    prov = self.adb.provision_silent(force=False, quiet=not watch_enabled)
                    report["provision"] = prov
                    if not prov.get("provisioned"):
                        report["ok"] = False
                        report["errors"].append(f"Device provisioning failed: {prov}")
                        return report

            # Start live watcher (opens scrcpy if --watch was passed)
            watcher.start()

            if spec.check_crashes or spec.collect_logs:
                self.adb.clear_logs()

            # 2. Push workspace files onto the Android device before task runs
            for push_item in spec.push_files:
                if ":" in push_item and not Path(push_item).exists():
                    local_p, remote_p = push_item.rsplit(":", 1)
                else:
                    local_p, remote_p = push_item, "/sdcard/Download/"
                self._log_watch(watch_enabled, f"Pushing {local_p} -> {remote_p}")
                pushed = self.adb.push_file(local_p, remote_p)
                report["pushed_files"].append(pushed)

            # 3. Set clipboard if requested
            if spec.set_clipboard is not None:
                self.helper.action("clipboard", text=spec.set_clipboard)
                self.adb.set_clipboard(spec.set_clipboard)

            # 4. Install APKs (from local file, URL, or F-Droid query/package) & auto-grant permissions
            primary_package: str | None = spec.locked_app_package
            for apk_src in spec.install_apks:
                self._log_watch(watch_enabled, f"Installing {apk_src} (auto-granting permissions)...")
                info: InstalledAppInfo = self.adb.install_apk(
                    apk_src,
                    grant_permissions=spec.grant_all_permissions,
                )
                report["installed_apks"].append(info.to_dict())
                if info.package and not primary_package:
                    primary_package = info.package

            # 5. Clear app data if requested
            clear_targets = list(spec.clear_packages)
            if "auto" in clear_targets:
                clear_targets = [p for p in clear_targets if p != "auto"]
                if primary_package:
                    clear_targets.append(primary_package)
            for pkg in clear_targets:
                ok = self.adb.clear_app_data(pkg)
                report["cleared_packages"].append({"package": pkg, "cleared": ok})
                if spec.grant_all_permissions:
                    self.adb.grant_all_permissions(pkg)

            # 6. Grant all permissions to any explicitly specified packages
            for pkg in spec.grant_packages:
                target_pkg = primary_package if pkg == "auto" else pkg
                if target_pkg:
                    perms, ops = self.adb.grant_all_permissions(target_pkg)
                    report["granted_packages"].append(
                        {"package": target_pkg, "permissions": perms, "appops": ops}
                    )

            # 7. Launch app if requested
            if spec.launch_target:
                target_launch = (
                    primary_package if spec.launch_target == "auto" else spec.launch_target
                )
                if target_launch:
                    self._log_watch(watch_enabled, f"Launching {target_launch}...")
                    launch_res = self.adb.launch_app(target_launch)
                    report["launched_app"] = launch_res
                    if not launch_res.get("launched"):
                        report["errors"].append(f"Failed to launch {target_launch}")

            # 8. Open URLs / deep links if requested
            for uri in spec.open_urls:
                self._log_watch(watch_enabled, f"Opening URI {uri}...")
                opened = self.adb.open_url(uri, package=spec.locked_app_package)
                report["opened_urls"].append(opened)

            # 9. Pre-shell commands
            for cmd in spec.pre_shell:
                out = self.adb.user_shell(cmd)
                report["pre_shell_outputs"].append({"cmd": cmd, "output": out})

            # 10. Compound Semantic & Coordinate UI actions (adaptive micro-settle, zero blind sleeps)
            total_actions = len(spec.ui_actions)
            for idx, act in enumerate(spec.ui_actions, 1):
                act_type = str(act.get("type") or act.get("cmd") or "").lower()
                self._log_watch(watch_enabled, f"[Step {idx}] {act_type}: {act}")
                res = self._execute_ui_action(act_type, act)
                report["ui_actions_executed"].append({"step": idx, "action": act, "result": res})
                if not res.get("success", True):
                    report["ok"] = False
                    report["errors"].append(
                        res.get("error") or f"UI action {act_type} failed at step {idx}"
                    )
                    break
                passive = act_type in (
                    "wait_text", "wait-text", "wait_any", "wait-any",
                    "wait_gone", "wait-gone", "wait_stable", "capture", "extract", "sleep",
                ) or bool(res.get("skipped"))
                if idx < total_actions:
                    next_type = str(
                        spec.ui_actions[idx].get("type") or spec.ui_actions[idx].get("cmd") or ""
                    ).lower()
                    next_waits = next_type in (
                        "wait_text", "wait-text", "wait_any", "wait-any",
                        "wait_gone", "wait-gone", "wait_stable",
                    )
                    if not passive and not next_waits:
                        time.sleep(0.50 if act_type in ("type", "fill") else 0.06)
                elif not passive and (spec.pull_files or spec.assert_texts or spec.post_shell):
                    time.sleep(0.25)

            if self.engine.vars:
                report["captured_vars"] = dict(self.engine.vars)

            # 11. Wait for text on screen if specified
            for text_needle in spec.wait_for_text:
                rendered_needle = str(self.engine.render_vars(text_needle))
                found = self._wait_for_text(rendered_needle, timeout=25.0)
                report["assertions"].append(
                    {"type": "wait_for_text", "text": rendered_needle, "passed": found}
                )
                if not found:
                    report["ok"] = False
                    report["errors"].append(f"Timed out waiting for text on screen: {rendered_needle!r}")

            # 13. Post-execution text assertions
            if spec.assert_texts:
                ui_now = self.helper.dump_compact_ui(max_elements=100)
                screen_blob = json.dumps(ui_now.get("elements", []), ensure_ascii=False).lower()
                for expected_txt in spec.assert_texts:
                    rendered_exp = str(self.engine.render_vars(expected_txt))
                    passed = rendered_exp.lower() in screen_blob
                    report["assertions"].append(
                        {"type": "assert_text", "text": rendered_exp, "passed": passed}
                    )
                    if not passed:
                        report["ok"] = False
                        report["errors"].append(
                            f"Assertion failed: expected text {rendered_exp!r} not visible on screen"
                        )

            # 14. Post-shell commands
            for cmd in spec.post_shell:
                out = self.adb.user_shell(cmd)
                report["post_shell_outputs"].append({"cmd": cmd, "output": out})

            # 15. Pull files generated/downloaded on the device back to the AI workspace
            for pull_item in spec.pull_files:
                if ":" in pull_item:
                    remote_p, local_p = pull_item.split(":", 1)
                else:
                    remote_p, local_p = pull_item, "./artifacts/"
                pulled = self.adb.pull_file(remote_p, local_p)
                report["pulled_files"].append(pulled)

            # 16. Read clipboard & active notifications if requested
            if spec.get_clipboard:
                report["clipboard"] = self.adb.get_clipboard()
            if spec.read_notifications:
                report["notifications"] = self.adb.get_notifications()

            # 17. Crash & ANR inspection
            if spec.check_crashes:
                crashes = self.adb.collect_crashes(package_filter=primary_package)
                report["crashes"] = crashes.to_dict()
                if crashes.has_crashes:
                    report["ok"] = False
                    report["errors"].append(
                        f"Detected crash/ANR on device (fatal={len(crashes.fatal_exceptions)}, "
                        f"anr={len(crashes.anrs)}, native={len(crashes.native_tombstones)})"
                    )

            # 18. Logcat tail collection
            if spec.collect_logs:
                report["logcat_tail"] = self.adb.collect_logcat_tail(
                    lines=spec.log_lines,
                    package_filter=primary_package,
                    errors_only=False,
                )

            # 19. Screenshot capture
            if spec.screenshot_path:
                saved = self.adb.screenshot(spec.screenshot_path)
                report["screenshot"] = saved

            # 20. Compact UI hierarchy summary (enabled by default so host AI agent sees current screen)
            if spec.dump_ui:
                report["ui_summary"] = self.helper.dump_compact_ui()

            # 21. Optional app stop after task
            if spec.stop_after and primary_package:
                self.adb.stop_app(primary_package)

        except Exception as exc:
            report["ok"] = False
            report["errors"].append(str(exc))
        finally:
            watcher.stop()
            self.helper.close()
            report["duration_sec"] = round(time.monotonic() - started, 2)

        return report

    def _execute_ui_action(self, act_type: str, act: dict[str, Any]) -> dict[str, Any]:
        return self.engine.execute_action(act)

    def _wait_for_text(self, text_needle: str, timeout: float = 25.0) -> bool:
        return self.engine._wait_for_text(text_needle, timeout=timeout)
