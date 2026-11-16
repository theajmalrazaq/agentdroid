#!/usr/bin/env python3
"""
AgentDroid Real-App End-to-End (E2E) Verified Benchmark Suite.

Runs 4 genuine multi-step application workflows on live hardware/Redroid via
AgentDroid's CompoundPipeline, AndroidEngine, and headless CLI, verifying state
changes cleanly without false-positive assertions:
  1. Markor: push markdown note -> launch/edit append -> save -> pull & verify content delta
  2. DeskClock: clean reset -> baseline count -> add alarm -> verify clock + ON count delta (+1)
  3. Settings CLI: full subprocess `agentdroid run --headless` app audit for Markor Permissions/Storage
  4. Fossify Math: fresh `adb install` (org.fossify.math, 7.0 MB) + CLI `42 + 58 = 100` UI verification

Usage:
    python3 benchmarks/run_actual_app_benchmark.py [--serial 127.0.0.1:5555]
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.pipeline import CompoundPipeline, PipelineSpec

FOSSIFY_APK = Path.home() / ".cache" / "agentdroid" / "apks" / "org.fossify.math_10.apk"
RESULTS_PATH = PROJECT_ROOT / "benchmarks" / "results" / "benchmark_actual_apps_results.json"


def run_cli_json(args: list[str], timeout: float = 90.0) -> tuple[float, dict[str, Any]]:
    """Run `agentdroid run ... -j` subprocess and return (wall_sec, parsed_json)."""
    t0 = time.perf_counter()
    proc = subprocess.run(
        ["agentdroid", *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    wall_sec = time.perf_counter() - t0
    if not proc.stdout.strip():
        raise RuntimeError(f"agentdroid returned empty stdout (rc={proc.returncode}): {proc.stderr}")
    data = json.loads(proc.stdout)
    return wall_sec, data


def task1_markor_note_workflow(dev: AdbDevice) -> dict[str, Any]:
    """Task 1: Push Markdown template, append line inside Markor editor, save, pull & diff."""
    remote_path = "/sdcard/Download/agentdroid_bench_task1.md"
    local_in = Path("/tmp/agentdroid_task1_in.md")
    local_out = Path("/tmp/agentdroid_task1_pulled.md")
    initial_text = "# AgentDroid E2E Benchmark\nStatus: Pending\nNotes:\n"
    append_marker = "Verified live benchmark PASSED"

    local_in.write_text(initial_text)
    local_out.unlink(missing_ok=True)
    dev.shell("am force-stop net.gsantner.markor")
    dev.shell(f"rm -f {remote_path}")

    t0 = time.perf_counter()
    spec = PipelineSpec.from_dict(
        {
            "serial": dev.serial,
            "headless": True,
            "auto_provision": False,
            "push_files": [f"{local_in}:{remote_path}"],
            "open_url": f"file://{remote_path}",
            "ui_actions": [
                {"type": "wait_text", "text": "Status"},
                {"type": "click", "selector": "document__fragment__edit__highlighting_editor"},
                {"type": "type", "text": f"\n{append_marker}", "append": True},
                {"type": "click", "selector": "Save"},
            ],
            "pull_files": [f"{remote_path}:{local_out}"],
            "check_crashes": True,
        }
    )
    report = CompoundPipeline(spec).run()
    wall_sec = time.perf_counter() - t0

    pulled_text = local_out.read_text() if local_out.exists() else ""
    header_intact = "# AgentDroid E2E Benchmark" in pulled_text
    marker_present = append_marker in pulled_text
    bytes_grew = len(pulled_text.encode("utf-8")) > len(initial_text.encode("utf-8"))
    passed = bool(
        report.get("ok")
        and header_intact
        and marker_present
        and bytes_grew
        and not report.get("crashes", {}).get("has_crashes")
    )

    return {
        "task": "markor_markdown_edit_verify",
        "method": "CompoundPipeline (single turn, append=True)",
        "ok": passed,
        "wall_clock_sec": round(wall_sec, 3),
        "pipeline_duration_sec": report.get("duration_sec"),
        "steps_executed": len(report.get("ui_actions_executed", [])),
        "llm_turns_required": 1,
        "initial_bytes": len(initial_text.encode("utf-8")),
        "pulled_bytes": len(pulled_text.encode("utf-8")),
        "verification": {
            "header_intact": header_intact,
            "marker_present": marker_present,
            "bytes_grew": bytes_grew,
            "crashes": bool(report.get("crashes", {}).get("has_crashes")),
            "pulled_preview": pulled_text,
        },
        "errors": report.get("errors", []),
    }


def _count_deskclock_alarms(helper: AccessibilityHelperClient) -> tuple[int, int, list[dict[str, Any]]]:
    dump = helper.dump_compact_ui(max_elements=80)
    elements = dump.get("elements", [])
    clocks = [e for e in elements if e.get("resource_id") == "digital_clock"]
    on_switches = [
        e for e in elements if e.get("resource_id") == "onoff" and e.get("label") == "ON"
    ]
    return len(clocks), len(on_switches), clocks


def task2_deskclock_add_alarm(dev: AdbDevice, helper: AccessibilityHelperClient, engine: AndroidEngine) -> dict[str, Any]:
    """Task 2: Clean DeskClock state -> baseline alarm count -> create alarm -> verify +1 clock & +1 ON."""
    dev.shell("pm clear com.android.deskclock")
    time.sleep(0.5)

    t0 = time.perf_counter()
    launch_info = dev.launch_app("com.android.deskclock")
    engine.execute_action({"type": "wait_text", "text": "Alarm", "timeout": 8.0})
    engine.execute_action({"type": "click", "selector": "Alarm"})
    time.sleep(0.4)

    before_clocks, before_on, _ = _count_deskclock_alarms(helper)

    steps = [
        {"type": "click", "selector": "Add alarm"},
        {"type": "wait_text", "text": "OK", "timeout": 5.0},
        {"type": "click", "selector": "OK"},
    ]
    executed = [engine.execute_action(step) for step in steps]
    time.sleep(0.6)

    after_clocks, after_on, after_items = _count_deskclock_alarms(helper)
    wall_sec = time.perf_counter() - t0

    passed = (after_clocks == before_clocks + 1) and (after_on == before_on + 1)
    # Clean up alarm state so background alarms do not trigger later
    dev.shell("pm clear com.android.deskclock")

    return {
        "task": "deskclock_add_alarm_verify",
        "method": "AndroidEngine UI navigation + state delta assertion",
        "ok": passed,
        "wall_clock_sec": round(wall_sec, 3),
        "launch_WaitTime_ms": launch_info.get("wait_time_ms"),
        "steps_executed": 1 + len(steps),  # Alarm tab + Add alarm + wait OK + OK
        "llm_turns_required": 1,
        "verification": {
            "before_digital_clock_count": before_clocks,
            "after_digital_clock_count": after_clocks,
            "before_on_switch_count": before_on,
            "after_on_switch_count": after_on,
            "clock_delta": after_clocks - before_clocks,
            "on_switch_delta": after_on - before_on,
            "final_clocks": [c.get("label") for c in after_items],
        },
        "action_results": executed,
    }


def task3_settings_app_audit_cli(serial: str) -> dict[str, Any]:
    """Task 3: Real `agentdroid run --headless` CLI navigation into Settings -> Apps -> Markor."""
    wall_sec, data = run_cli_json(
        [
            "run",
            "-s",
            serial,
            "--headless",
            "--no-provision",
            "--clear-data",
            "com.android.settings",
            "--launch",
            "com.android.settings",
            "-d",
            "wait_text:Apps & notifications",
            "-d",
            "click:Apps & notifications",
            "-d",
            "wait_text:SEE ALL",
            "-d",
            "click:SEE ALL",
            "-d",
            "wait_text:App info",
            "-d",
            "scroll_to:Markor",
            "-d",
            "click:Markor",
            "-d",
            "wait_text:Permissions",
            "--assert-text",
            "Permissions",
            "--assert-text",
            "Storage",
            "-j",
        ]
    )
    assertions_ok = bool(data.get("assertions")) and all(a.get("passed") for a in data["assertions"])
    passed = bool(data.get("ok") and assertions_ok and not data.get("crashes", {}).get("has_crashes"))
    return {
        "task": "settings_markor_app_info_audit",
        "method": "Subprocess `agentdroid run --headless` compound CLI",
        "ok": passed,
        "subprocess_wall_sec": round(wall_sec, 3),
        "reported_duration_sec": data.get("duration_sec"),
        "steps_executed": len(data.get("ui_actions_executed", [])),
        "llm_turns_required": 1,
        "foreground": data.get("ui_summary", {}).get("foreground"),
        "assertions": data.get("assertions"),
        "crashes": data.get("crashes", {}).get("has_crashes"),
        "errors": data.get("errors", []),
    }


def task4_fossify_math_install_and_compute(dev: AdbDevice) -> dict[str, Any]:
    """Task 4: Fresh install of Fossify Math (7.0 MB, Mobilebox parity APK) + CLI `42 + 58 = 100`."""
    if not FOSSIFY_APK.exists():
        raise FileNotFoundError(f"Missing Fossify Math APK: {FOSSIFY_APK}")

    dev.shell("pm uninstall org.fossify.math")
    t_inst0 = time.perf_counter()
    inst = dev.run_adb(["install", "-g", str(FOSSIFY_APK)], timeout=120)
    install_ms = (time.perf_counter() - t_inst0) * 1000.0
    if inst.returncode != 0 or "Success" not in inst.stdout:
        raise RuntimeError(f"Fossify Math install failed: {inst.stdout} {inst.stderr}")

    wall_sec, data = run_cli_json(
        [
            "run",
            "-s",
            dev.serial,
            "--headless",
            "--no-provision",
            "--clear-data",
            "org.fossify.math",
            "--launch",
            "org.fossify.math",
            "-d",
            "wait_text:7",
            "-d",
            "click:btn_4",
            "-d",
            "click:btn_2",
            "-d",
            "click:btn_plus",
            "-d",
            "click:btn_5",
            "-d",
            "click:btn_8",
            "-d",
            "click:btn_equals",
            "--assert-text",
            "100",
            "-j",
        ]
    )
    result_el = [
        e for e in data.get("ui_summary", {}).get("elements", []) if e.get("resource_id") == "result"
    ]
    result_text = result_el[0].get("label") if result_el else None
    passed = bool(data.get("ok") and result_text == "100" and not data.get("crashes", {}).get("has_crashes"))
    return {
        "task": "fossify_math_fresh_install_and_compute_e2e",
        "method": "Real `adb install` + subprocess `agentdroid run --headless` (42 + 58 = 100)",
        "ok": passed,
        "apk_bytes": FOSSIFY_APK.stat().st_size,
        "fresh_install_ms": round(install_ms, 2),
        "subprocess_wall_sec": round(wall_sec, 3),
        "reported_duration_sec": data.get("duration_sec"),
        "combined_install_plus_e2e_sec": round((install_ms / 1000.0) + wall_sec, 3),
        "steps_executed": len(data.get("ui_actions_executed", [])),
        "llm_turns_required": 1,
        "result_display_label": result_text,
        "assertions": data.get("assertions"),
        "crashes": data.get("crashes", {}).get("has_crashes"),
        "errors": data.get("errors", []),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run AgentDroid real-app E2E benchmarks.")
    parser.add_argument("-s", "--serial", default="127.0.0.1:5555")
    args = parser.parse_args()

    dev = AdbDevice(serial=args.serial)
    if not dev.connect(timeout=5.0):
        raise RuntimeError(f"Cannot connect to {args.serial}")
    helper = AccessibilityHelperClient(dev)
    if not helper.ensure_ready():
        raise RuntimeError("Artemis Accessibility Helper is not ready")
    engine = AndroidEngine(adb=dev)

    print("=== AgentDroid Real-App E2E Benchmark Suite ===")
    t1 = task1_markor_note_workflow(dev)
    print(f"  Task 1 (Markor): ok={t1['ok']} wall={t1['wall_clock_sec']}s bytes={t1['initial_bytes']}->{t1['pulled_bytes']}")

    t2 = task2_deskclock_add_alarm(dev, helper, engine)
    print(
        f"  Task 2 (DeskClock): ok={t2['ok']} wall={t2['wall_clock_sec']}s "
        f"clocks={t2['verification']['before_digital_clock_count']}->{t2['verification']['after_digital_clock_count']}"
    )

    t3 = task3_settings_app_audit_cli(args.serial)
    print(f"  Task 3 (Settings CLI): ok={t3['ok']} wall={t3['subprocess_wall_sec']}s dur={t3['reported_duration_sec']}s")

    t4 = task4_fossify_math_install_and_compute(dev)
    print(
        f"  Task 4 (Fossify Math): ok={t4['ok']} install={t4['fresh_install_ms']}ms "
        f"e2e_wall={t4['subprocess_wall_sec']}s result={t4['result_display_label']}"
    )

    tasks = [t1, t2, t3, t4]
    all_passed = all(t["ok"] for t in tasks)
    payload = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "device_serial": args.serial,
        "helper_version": (helper.ping() or {}).get("version_name"),
        "all_passed": all_passed,
        "tasks": tasks,
    }

    payload_text = json.dumps(payload, indent=2) + "\n"
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(payload_text)
    artifact_dir = os.environ.get("AGENTDROID_BENCHMARK_ARTIFACT_DIR")
    if artifact_dir:
        art_path = Path(artifact_dir).expanduser() / RESULTS_PATH.name
        art_path.parent.mkdir(parents=True, exist_ok=True)
        art_path.write_text(payload_text)
    print(f"Saved E2E results (all_passed={all_passed}) to {RESULTS_PATH}")
    if not all_passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
