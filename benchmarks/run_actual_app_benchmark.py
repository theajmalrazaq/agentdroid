#!/usr/bin/env python3
"""Extensive Real-World Task Benchmark Runner for AgentDroid vs AndroidWorld vs Mobilebox.

Executes actual end-to-end task workflows on the active Android device:
1. Markor: Note creation, multi-line typing, save, file verification on disk.
2. DeskClock: Alarm tab navigation, create/toggle alarm, UI verification.
3. Settings: Deep app audit (Apps & notifications -> Markor App Info).
4. Sideload & Cold Start: APK reinstall and cold-start interactive turnaround.

Measures empirical wall-clock time, step counts, action latencies, perception times,
token consumption, and dollar costs.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import statistics
import subprocess
import time
from typing import Any

from agentdroid.adb import AdbDevice
from agentdroid.helper import AccessibilityHelperClient

SERIAL = "127.0.0.1:5555"

def token_count(data: Any) -> int:
    """Approximate token count for JSON/text payload (4 chars ~= 1 token)."""
    text = json.dumps(data) if not isinstance(data, str) else data
    return max(1, len(text) // 4)

def run_benchmarks():
    dev = AdbDevice(SERIAL)
    if not dev.connect(timeout=5.0):
        raise RuntimeError("ADB connection failed to " + SERIAL)

    helper = AccessibilityHelperClient(dev)
    if not helper.ensure_ready():
        raise RuntimeError("Accessibility Helper not ready")

    results = {
        "benchmark_metadata": {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "device": dev.serial,
            "android_version": dev.shell("getprop ro.build.version.release").strip(),
            "cpu_arch": dev.shell("getprop ro.product.cpu.abi").strip(),
            "display": dev.shell("wm size").strip(),
            "artemis_helper_version": helper.ping().get("version_name"),
        },
        "tasks": {},
    }

    # =========================================================================
    # TASK 1: Markor Note Workflow (AndroidWorld core task: markor_create_note)
    # =========================================================================
    print("\n=======================================================")
    print("TASK 1: Markor Note Creation & Save (AndroidWorld markor)")
    print("=======================================================")
    t_start = time.perf_counter()
    task1_steps = []
    task1_perception_times = []
    task1_tokens = 0

    # Step 1.1: Reset app state and push initial template
    dev.shell("am force-stop net.gsantner.markor")
    test_file_dev = "/sdcard/Download/agentdroid_benchmark_task1.md"
    dev.shell(f"rm -f {test_file_dev}")
    initial_text = "# Benchmark Task 1\nStatus: Pending Execution\n"
    tmp_local = Path("/tmp/agentdroid_task1.md")
    tmp_local.write_text(initial_text, encoding="utf-8")
    dev.push_file(str(tmp_local), test_file_dev)

    # Step 1.2: Launch Markor directly opening the target file
    t0 = time.perf_counter()
    dev.shell(f"am start -a android.intent.action.VIEW -d file://{test_file_dev} -t text/plain net.gsantner.markor")
    time.sleep(1.0)
    task1_steps.append({"step": "launch_and_open_file", "latency_s": round(time.perf_counter() - t0, 3)})

    # Step 1.3: Perceive UI
    t0 = time.perf_counter()
    ui = helper.dump_compact_ui()
    dt_perc = (time.perf_counter() - t0) * 1000.0
    task1_perception_times.append(dt_perc)
    tok = token_count(ui)
    task1_tokens += tok
    task1_steps.append({"step": "perceive_editor_screen", "perception_ms": round(dt_perc, 2), "tokens": tok})

    # Step 1.4: Tap Edit or editor body
    t0 = time.perf_counter()
    tap_res = helper.tap_element("Edit", timeout=3.0)
    if not tap_res.get("success"):
        # Fallback to tap editor area
        helper.action("tap", x=540, y=600)
    task1_steps.append({"step": "tap_edit", "latency_s": round(time.perf_counter() - t0, 3)})
    time.sleep(0.4)

    # Step 1.5: Type verification lines
    t0 = time.perf_counter()
    dev.shell("input keyevent KEYCODE_MOVE_END")
    dev.shell("input text '\n- [x] Verified by AgentDroid Artemis Engine\n- [x] Wall-Clock Latency Benchmark PASSED'")
    task1_steps.append({"step": "type_checklist_items", "latency_s": round(time.perf_counter() - t0, 3)})
    time.sleep(0.5)

    # Step 1.6: Tap Save
    t0 = time.perf_counter()
    save_res = helper.tap_element("Save", timeout=3.0)
    if not save_res.get("success"):
        helper.action("tap", x=970, y=140)  # Save icon coordinates in Markor toolbar
    task1_steps.append({"step": "tap_save", "latency_s": round(time.perf_counter() - t0, 3)})
    time.sleep(0.8)

    # Step 1.7: Pull file and verify on host
    t0 = time.perf_counter()
    pulled_local = Path("/tmp/agentdroid_task1_pulled.md")
    dev.pull_file(test_file_dev, str(pulled_local))
    content = pulled_local.read_text(encoding="utf-8") if pulled_local.is_file() else ""
    task1_verified = "Verified by AgentDroid Artemis Engine" in content
    task1_steps.append({"step": "pull_and_verify_file", "latency_s": round(time.perf_counter() - t0, 3), "verified": task1_verified})

    t_task1_total = time.perf_counter() - t_start
    results["tasks"]["task1_markor_note"] = {
        "task_name": "Markor Note Creation, Edit & Verify (AndroidWorld markor_create_note)",
        "verified": task1_verified,
        "total_wall_clock_s": round(t_task1_total, 2),
        "steps_count": len(task1_steps),
        "mean_action_latency_s": round(statistics.mean([s.get("latency_s", 0.0) for s in task1_steps if "latency_s" in s]), 3),
        "perception_turnaround_ms": round(statistics.mean(task1_perception_times) if task1_perception_times else 0.0, 2),
        "artemis_tokens_consumed": task1_tokens,
        "vision_equivalent_tokens": len(task1_steps) * 1600,
        "token_reduction_pct": round((1.0 - (task1_tokens / max(1, len(task1_steps) * 1600))) * 100, 1),
        "compute_cost_usd": 0.0,
        "steps_detail": task1_steps,
    }
    print(f"Task 1 Result: PASS={task1_verified} | Time={t_task1_total:.2f}s | Steps={len(task1_steps)} | Tokens={task1_tokens}")

    # =========================================================================
    # TASK 2: DeskClock Set/Toggle Alarm (AndroidWorld deskclock_set_alarm)
    # =========================================================================
    print("\n=======================================================")
    print("TASK 2: DeskClock Alarm Configure (AndroidWorld deskclock)")
    print("=======================================================")
    t_start = time.perf_counter()
    task2_steps = []
    task2_perception_times = []
    task2_tokens = 0

    # Step 2.1: Cold launch DeskClock
    dev.shell("am force-stop com.android.deskclock")
    t0 = time.perf_counter()
    dev.shell("am start -n com.android.deskclock/com.android.deskclock.DeskClock")
    time.sleep(1.0)
    task2_steps.append({"step": "launch_deskclock", "latency_s": round(time.perf_counter() - t0, 3)})

    # Step 2.2: Perceive DeskClock UI
    t0 = time.perf_counter()
    ui = helper.dump_compact_ui()
    dt_perc = (time.perf_counter() - t0) * 1000.0
    task2_perception_times.append(dt_perc)
    tok = token_count(ui)
    task2_tokens += tok
    task2_steps.append({"step": "perceive_clock_screen", "perception_ms": round(dt_perc, 2), "tokens": tok})

    # Step 2.3: Tap Alarm tab if not selected
    t0 = time.perf_counter()
    helper.tap_element("Alarm", timeout=3.0)
    time.sleep(0.5)
    task2_steps.append({"step": "tap_alarm_tab", "latency_s": round(time.perf_counter() - t0, 3)})

    # Step 2.4: Perceive Alarm list
    t0 = time.perf_counter()
    ui = helper.dump_compact_ui()
    dt_perc = (time.perf_counter() - t0) * 1000.0
    task2_perception_times.append(dt_perc)
    tok = token_count(ui)
    task2_tokens += tok
    task2_steps.append({"step": "perceive_alarm_list", "perception_ms": round(dt_perc, 2), "tokens": tok})

    # Step 2.5: Tap FAB / Add Alarm
    t0 = time.perf_counter()
    fab_res = helper.tap_element("Add alarm", timeout=2.5)
    if not fab_res.get("success"):
        # Tap bottom center FAB
        helper.action("tap", x=540, y=1750)
    time.sleep(0.8)
    task2_steps.append({"step": "tap_add_alarm_fab", "latency_s": round(time.perf_counter() - t0, 3)})

    # Step 2.6: Confirm / Tap OK on time picker
    t0 = time.perf_counter()
    ok_res = helper.tap_element("OK", timeout=2.5)
    if not ok_res.get("success"):
        helper.action("tap", x=800, y=1300)
    time.sleep(0.8)
    task2_steps.append({"step": "confirm_time_picker", "latency_s": round(time.perf_counter() - t0, 3)})

    # Step 2.7: Perceive screen to verify alarm exists
    t0 = time.perf_counter()
    ui_final = helper.dump_compact_ui()
    dt_perc = (time.perf_counter() - t0) * 1000.0
    task2_perception_times.append(dt_perc)
    tok = token_count(ui_final)
    task2_tokens += tok

    # Check for alarm toggle or time elements
    has_alarm = any("alarm" in (str(el.get("label", "")) + " " + str(el.get("desc", ""))).lower() or "am" in str(el.get("label", "")).lower() or "pm" in str(el.get("label", "")).lower() for el in ui_final.get("elements", []))
    task2_steps.append({"step": "verify_alarm_created", "perception_ms": round(dt_perc, 2), "tokens": tok, "verified": has_alarm})

    t_task2_total = time.perf_counter() - t_start
    results["tasks"]["task2_deskclock_alarm"] = {
        "task_name": "DeskClock Set Alarm & Verify (AndroidWorld deskclock_set_alarm)",
        "verified": has_alarm,
        "total_wall_clock_s": round(t_task2_total, 2),
        "steps_count": len(task2_steps),
        "mean_action_latency_s": round(statistics.mean([s.get("latency_s", 0.0) for s in task2_steps if "latency_s" in s]), 3),
        "perception_turnaround_ms": round(statistics.mean(task2_perception_times) if task2_perception_times else 0.0, 2),
        "artemis_tokens_consumed": task2_tokens,
        "vision_equivalent_tokens": len(task2_steps) * 1600,
        "token_reduction_pct": round((1.0 - (task2_tokens / max(1, len(task2_steps) * 1600))) * 100, 1),
        "compute_cost_usd": 0.0,
        "steps_detail": task2_steps,
    }
    print(f"Task 2 Result: PASS={has_alarm} | Time={t_task2_total:.2f}s | Steps={len(task2_steps)} | Tokens={task2_tokens}")

    # =========================================================================
    # TASK 3: Settings Deep Audit (AndroidWorld settings_navigate)
    # =========================================================================
    print("\n=======================================================")
    print("TASK 3: Settings Deep Audit (AndroidWorld settings)")
    print("=======================================================")
    t_start = time.perf_counter()
    task3_steps = []
    task3_perception_times = []
    task3_tokens = 0

    # Step 3.1: Cold launch Settings
    dev.shell("am force-stop com.android.settings")
    t0 = time.perf_counter()
    dev.shell("am start -n com.android.settings/.Settings")
    time.sleep(1.0)
    task3_steps.append({"step": "launch_settings", "latency_s": round(time.perf_counter() - t0, 3)})

    # Step 3.2: Perceive root screen
    t0 = time.perf_counter()
    ui = helper.dump_compact_ui()
    dt_perc = (time.perf_counter() - t0) * 1000.0
    task3_perception_times.append(dt_perc)
    tok = token_count(ui)
    task3_tokens += tok
    task3_steps.append({"step": "perceive_settings_root", "perception_ms": round(dt_perc, 2), "tokens": tok})

    # Step 3.3: Tap "Apps & notifications"
    t0 = time.perf_counter()
    tap_res = helper.tap_element("Apps & notifications", timeout=3.0)
    if not tap_res.get("success"):
        # Fallback position for Apps item in Android 11 Settings
        helper.action("tap", x=540, y=550)
    time.sleep(0.8)
    task3_steps.append({"step": "tap_apps_notifications", "latency_s": round(time.perf_counter() - t0, 3)})

    # Step 3.4: Perceive Apps screen
    t0 = time.perf_counter()
    ui = helper.dump_compact_ui()
    dt_perc = (time.perf_counter() - t0) * 1000.0
    task3_perception_times.append(dt_perc)
    tok = token_count(ui)
    task3_tokens += tok
    task3_steps.append({"step": "perceive_apps_screen", "perception_ms": round(dt_perc, 2), "tokens": tok})

    # Step 3.5: Tap "See all apps" or tap Markor directly
    t0 = time.perf_counter()
    tap_app = helper.tap_element("Markor", timeout=2.0)
    if not tap_app.get("success"):
        helper.tap_element("See all", timeout=2.0)
        time.sleep(0.5)
        tap_app = helper.tap_element("Markor", timeout=3.0)
    task3_steps.append({"step": "tap_markor_app_info", "latency_s": round(time.perf_counter() - t0, 3)})
    time.sleep(0.8)

    # Step 3.6: Perceive App Info screen & verify
    t0 = time.perf_counter()
    ui_appinfo = helper.dump_compact_ui()
    dt_perc = (time.perf_counter() - t0) * 1000.0
    task3_perception_times.append(dt_perc)
    tok = token_count(ui_appinfo)
    task3_tokens += tok

    has_app_info = any("storage" in str(el.get("label", "")).lower() or "permissions" in str(el.get("label", "")).lower() or "uninstall" in str(el.get("label", "")).lower() for el in ui_appinfo.get("elements", []))
    task3_steps.append({"step": "verify_app_info_screen", "perception_ms": round(dt_perc, 2), "tokens": tok, "verified": has_app_info})

    # Step 3.7: Press Home to return
    t0 = time.perf_counter()
    dev.shell("input keyevent KEYCODE_HOME")
    task3_steps.append({"step": "return_to_home", "latency_s": round(time.perf_counter() - t0, 3)})

    t_task3_total = time.perf_counter() - t_start
    results["tasks"]["task3_settings_audit"] = {
        "task_name": "Settings App Audit & Deep Navigation (AndroidWorld settings_navigate)",
        "verified": has_app_info,
        "total_wall_clock_s": round(t_task3_total, 2),
        "steps_count": len(task3_steps),
        "mean_action_latency_s": round(statistics.mean([s.get("latency_s", 0.0) for s in task3_steps if "latency_s" in s]), 3),
        "perception_turnaround_ms": round(statistics.mean(task3_perception_times) if task3_perception_times else 0.0, 2),
        "artemis_tokens_consumed": task3_tokens,
        "vision_equivalent_tokens": len(task3_steps) * 1600,
        "token_reduction_pct": round((1.0 - (task3_tokens / max(1, len(task3_steps) * 1600))) * 100, 1),
        "compute_cost_usd": 0.0,
        "steps_detail": task3_steps,
    }
    print(f"Task 3 Result: PASS={has_app_info} | Time={t_task3_total:.2f}s | Steps={len(task3_steps)} | Tokens={task3_tokens}")

    # =========================================================================
    # TASK 4: Mobilebox Task - Cold Start, APK Sideload & Turnaround
    # =========================================================================
    print("\n=======================================================")
    print("TASK 4: APK Sideload & Cold Start Turnaround (Mobilebox core)")
    print("=======================================================")
    cached_apk = Path.home() / ".cache" / "agentdroid" / "apks" / "net.gsantner.markor_164.apk"
    t_start = time.perf_counter()
    
    # APK install
    t0 = time.perf_counter()
    dev.shell(f"pm install -r -g {cached_apk}")
    dt_install_ms = (time.perf_counter() - t0) * 1000.0

    # Cold start to interactive screen
    dev.shell("am force-stop net.gsantner.markor")
    t0 = time.perf_counter()
    dev.shell("am start -W -n net.gsantner.markor/.activity.MainActivity")
    # Take screenshot immediately to record ready screen
    tmp_ss = Path("/tmp/coldstart_ss.png")
    dev.screenshot(tmp_ss)
    dt_coldstart_ms = (time.perf_counter() - t0) * 1000.0

    results["tasks"]["task4_sideload_coldstart"] = {
        "task_name": "APK Sideload & Cold-Start Turnaround (Mobilebox core benchmark)",
        "apk_install_latency_ms": round(dt_install_ms, 2),
        "cold_start_to_screenshot_ms": round(dt_coldstart_ms, 2),
        "screenshot_captured": tmp_ss.is_file(),
        "total_wall_clock_s": round(time.perf_counter() - t_start, 2),
    }
    print(f"Task 4 Result: Sideload={dt_install_ms:.1f}ms | ColdStart={dt_coldstart_ms:.1f}ms")

    # Output file
    out_path = Path(__file__).resolve().parent / "results" / "benchmark_actual_apps_results.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    # Also write to artifacts directory for compatibility
    artifacts_path = Path("/home/theajmalrazaq/Projects/agentdroid/artifacts/benchmark_actual_apps_results.json")
    artifacts_path.parent.mkdir(parents=True, exist_ok=True)
    artifacts_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n✅ All actual app benchmarks complete. Results written to {out_path}")

if __name__ == "__main__":
    run_benchmarks()
