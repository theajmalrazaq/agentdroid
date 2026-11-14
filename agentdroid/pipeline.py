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
from agentdroid.artemis_bridge import ArtemisBridge, GoalExecutionResult
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.watcher import LiveWatcher


@dataclass
class PipelineSpec:
    """Specification for a compound single-call general-purpose Android AI workflow."""

    serial: str | None = None
    artemis_url: str | None = None
    headless: bool = True
    watch: bool = False
    watch_web: bool = False
    auto_provision: bool = True

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

    # Optional external Artemis daemon natural-language goals (if running Artemis server)
    goals: list[str] = field(default_factory=list)
    combine_goals: bool = True
    profile: str = "flash"
    expected_output: str | None = None
    locked_app_package: str | None = None
    verification_level: str | None = None
    explorer_mode: str | None = None
    until_output: bool = False
    max_attempts: int = 1
    timeout: float = 900.0

    # Diagnostics & outputs (dump_ui defaults to True so the host AI agent always gets screen state)
    check_crashes: bool = True
    collect_logs: bool = False
    log_lines: int = 60
    screenshot_path: str | None = None
    dump_ui: bool = True

    @classmethod
    def from_file(cls, path: str | Path) -> PipelineSpec:
        p = Path(path).expanduser().resolve()
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError(f"Pipeline file {p} must contain a JSON object")
        valid_fields = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_fields}
        return cls(**filtered)


def parse_do_step(step_str: str) -> dict[str, Any]:
    """Parse a compact `--do` step string like 'click:Login', 'fill:Email=a@b.com', 'scroll-to:Save'."""
    raw = step_str.strip()
    if ":" not in raw:
        return {"type": "click", "selector": raw}
    verb, arg = raw.split(":", 1)
    v = verb.strip().lower()
    arg = arg.strip()

    if v in ("click", "tap-text", "tap_text"):
        return {"type": "click", "selector": arg}
    if v == "tap":
        parts = [p.strip() for p in arg.split(",")]
        return {"type": "tap", "x": float(parts[0]), "y": float(parts[1])}
    if v in ("fill", "input"):
        if "=" in arg:
            sel, txt = arg.split("=", 1)
            return {"type": "fill", "selector": sel.strip(), "text": txt}
        return {"type": "type", "text": arg}
    if v == "type":
        return {"type": "type", "text": arg}
    if v == "scroll":
        return {"type": "scroll", "direction": arg or "down"}
    if v in ("scroll-to", "scroll_to"):
        return {"type": "scroll_to", "text": arg}
    if v in ("wait", "wait-text", "wait_text"):
        return {"type": "wait_text", "text": arg}
    if v == "key":
        return {"type": "key", "key": arg}
    if v in ("open", "url", "open-url"):
        return {"type": "open_url", "uri": arg}
    if v == "launch":
        return {"type": "launch", "package": arg}
    if v == "shell":
        return {"type": "shell", "cmd": arg}
    if v == "sleep":
        return {"type": "sleep", "seconds": float(arg or 1.0)}
    return {"type": "click", "selector": raw}


class CompoundPipeline:
    """Executes a complete multi-step Android workflow in one call to minimize AI agent token usage."""

    def __init__(self, spec: PipelineSpec) -> None:
        self.spec = spec
        self.adb = AdbDevice(serial=spec.serial)
        self.helper = AccessibilityHelperClient(self.adb)
        self.artemis = ArtemisBridge(
            base_url=spec.artemis_url,
            device_serial=self.adb.serial,
            default_profile=spec.profile,
        )

    def _log_watch(self, watch_enabled: bool, msg: str) -> None:
        if watch_enabled:
            print(f"[agentdroid:watch] {msg}", file=sys.stderr)

    def run(self) -> dict[str, Any]:
        started = time.monotonic()
        spec = self.spec
        watch_enabled = bool(spec.watch and not (spec.headless and not spec.watch))

        watcher = LiveWatcher(
            self.adb.serial,
            artemis_url=self.artemis.base_url,
            watch=watch_enabled,
            prefer_web=spec.watch_web,
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
            "agent_runs": [],
            "agent_output": None,
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
            # 1. Connect & silently provision device
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
                    time.sleep(0.5)

            # 8. Open URLs / deep links if requested
            for uri in spec.open_urls:
                self._log_watch(watch_enabled, f"Opening URI {uri}...")
                opened = self.adb.open_url(uri, package=spec.locked_app_package)
                report["opened_urls"].append(opened)
                time.sleep(0.5)

            # 9. Pre-shell commands
            for cmd in spec.pre_shell:
                out = self.adb.shell(cmd)
                report["pre_shell_outputs"].append({"cmd": cmd, "output": out})

            # 10. Compound Semantic & Coordinate UI actions (via Artemis Accessibility Helper)
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
                time.sleep(0.35)

            # 11. Wait for text on screen if specified
            for text_needle in spec.wait_for_text:
                found = self._wait_for_text(text_needle, timeout=15.0)
                report["assertions"].append(
                    {"type": "wait_for_text", "text": text_needle, "passed": found}
                )
                if not found:
                    report["ok"] = False
                    report["errors"].append(f"Timed out waiting for text on screen: {text_needle!r}")

            # 12. Optional Artemis natural-language goals (when using an external Artemis daemon)
            if spec.goals:
                goals_to_run: list[str]
                if spec.combine_goals and len(spec.goals) > 1:
                    numbered = "\n".join(f"{i}. {g}" for i, g in enumerate(spec.goals, 1))
                    goals_to_run = [
                        f"Execute the following steps in order on the device:\n{numbered}"
                    ]
                else:
                    goals_to_run = list(spec.goals)

                for goal_text in goals_to_run:
                    goal_res: GoalExecutionResult = self.artemis.execute_goal(
                        goal_text,
                        profile=spec.profile,
                        expected_output=spec.expected_output,
                        locked_app_package=spec.locked_app_package,
                        verification_level=spec.verification_level,
                        explorer_mode=spec.explorer_mode,
                        timeout=spec.timeout,
                        watcher=watcher,
                        until_output=spec.until_output,
                        max_attempts=spec.max_attempts,
                        ui_context_provider=self.helper.dump_compact_ui,
                    )
                    report["agent_runs"].append(goal_res.to_dict())
                    if goal_res.output is not None:
                        report["agent_output"] = goal_res.output
                    elif goal_res.explanation:
                        report["agent_output"] = goal_res.explanation

                    if not goal_res.succeeded:
                        report["ok"] = False
                        report["errors"].append(
                            goal_res.error or f"Agent goal failed with status '{goal_res.status}'"
                        )
                        break

            # 13. Post-execution text assertions
            if spec.assert_texts:
                ui_now = self.helper.dump_compact_ui(max_elements=100)
                screen_blob = json.dumps(ui_now.get("elements", []), ensure_ascii=False).lower()
                for expected_txt in spec.assert_texts:
                    passed = expected_txt.lower() in screen_blob
                    report["assertions"].append(
                        {"type": "assert_text", "text": expected_txt, "passed": passed}
                    )
                    if not passed:
                        report["ok"] = False
                        report["errors"].append(
                            f"Assertion failed: expected text {expected_txt!r} not visible on screen"
                        )

            # 14. Post-shell commands
            for cmd in spec.post_shell:
                out = self.adb.shell(cmd)
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
            report["duration_sec"] = round(time.monotonic() - started, 2)

        return report

    def _execute_ui_action(self, act_type: str, act: dict[str, Any]) -> dict[str, Any]:
        if act_type in ("click", "tap_text"):
            return self.helper.tap_element(str(act["selector"]))
        if act_type == "fill":
            return self.helper.fill_element(
                str(act["selector"]),
                str(act["text"]),
                submit=bool(act.get("submit", False)),
            )
        if act_type == "tap":
            return self.helper.action("tap", x=act["x"], y=act["y"])
        if act_type == "type":
            return self.helper.action("type", text=act["text"], append=bool(act.get("append", False)))
        if act_type == "swipe":
            return self.helper.action(
                "swipe",
                x1=act["x1"],
                y1=act["y1"],
                x2=act["x2"],
                y2=act["y2"],
                duration=act.get("duration", 300),
            )
        if act_type == "scroll":
            return self.helper.scroll(str(act.get("direction", "down")))
        if act_type == "scroll_to":
            return self.helper.scroll_to_text(str(act["text"]))
        if act_type == "wait_text":
            ok = self._wait_for_text(str(act["text"]), timeout=float(act.get("timeout", 15.0)))
            return {"success": ok, "text": act["text"]}
        if act_type == "key":
            return self.helper.action("global", action=act["key"])
        if act_type == "open_url":
            res = self.adb.open_url(str(act["uri"]))
            return {"success": bool(res.get("opened", True)), **res}
        if act_type == "launch":
            res = self.adb.launch_app(str(act["package"]))
            return {"success": bool(res.get("launched", True)), **res}
        if act_type == "shell":
            out = self.adb.shell(str(act["cmd"]))
            return {"success": True, "output": out}
        if act_type == "sleep":
            secs = float(act.get("seconds", 1.0))
            time.sleep(secs)
            return {"success": True, "slept": secs}
        return {"success": False, "error": f"Unknown ui_action type: {act_type}"}

    def _wait_for_text(self, text_needle: str, timeout: float = 15.0) -> bool:
        needle = text_needle.lower()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ui = self.helper.dump_compact_ui(max_elements=100)
            blob = json.dumps(ui.get("elements", []), ensure_ascii=False).lower()
            if needle in blob:
                return True
            time.sleep(0.6)
        return False
