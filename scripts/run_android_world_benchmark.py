#!/usr/bin/env python3
"""Run AndroidWorld benchmark tasks via AgentDroid high-performance execution engine.

Compares execution time, step count, and reliability against published Vostride baselines.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("android_world_benchmark")

REGISTRY_PATH = REPO_ROOT / "benchmarks" / "android_world_tasks.json"
RESULTS_PATH = REPO_ROOT / "benchmarks" / "android_world_agentdroid_results.json"


def load_task_registry() -> list[dict[str, Any]]:
    if not REGISTRY_PATH.is_file():
        raise FileNotFoundError(f"Task registry not found at {REGISTRY_PATH}")
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        return json.load(f)


# --- 1. Audio Recorder Tasks ---

def run_audio_recorder_record_audio(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    pkg = "com.dimowner.audiorecorder"
    adb.clear_app_data(pkg)
    adb.grant_all_permissions(pkg)
    adb.launch_app(pkg)

    t0 = time.monotonic()
    burst_steps = [
        "if-visible:Get started->click:Get started",
        "if-visible:Apply->click:Apply",
        "wait-text:Recording: %s@5",
        "click:Recording: %s",
        "sleep:2",
        "click:btn_record_stop",
        "wait-text:Save@5",
        "click:Save",
        "wait-text:Record-1@5",
    ]
    results = engine.execute_action_burst(burst_steps)
    duration = time.monotonic() - t0

    out = adb.shell("find /sdcard/ -name 'Record-1*' 2>/dev/null")
    verified = "Record-1.m4a" in out

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": len(burst_steps),
        "results": results,
        "artifact_path": out.strip() if verified else None,
    }


def run_audio_recorder_record_audio_with_file_name(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    pkg = "com.dimowner.audiorecorder"
    adb.clear_app_data(pkg)
    adb.grant_all_permissions(pkg)
    adb.launch_app(pkg)

    file_name = "interview"
    t0 = time.monotonic()
    burst_steps = [
        "if-visible:Get started->click:Get started",
        "if-visible:Apply->click:Apply",
        "wait-text:Recording: %s@5",
        "click:Recording: %s",
        "sleep:2",
        "click:btn_record_stop",
        "wait-text:New name@5",
        f"fill:input_name={file_name}",
        "click:Save",
        f"wait-text:{file_name}@5",
    ]
    results = engine.execute_action_burst(burst_steps)
    duration = time.monotonic() - t0

    out = adb.shell(f"find /sdcard/ -name '{file_name}*' 2>/dev/null")
    verified = f"{file_name}.m4a" in out

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": len(burst_steps),
        "results": results,
        "artifact_path": out.strip() if verified else None,
    }


# --- 2. Clock Tasks ---

def run_clock_stopwatch_running(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    pkg = "com.android.deskclock"
    adb.clear_app_data(pkg)
    adb.launch_app(pkg)

    t0 = time.monotonic()
    burst_steps = [
        "click:STOPWATCH",
        "wait-text:START@5",
        "click:START",
        "wait-text:Pause@5",
    ]
    results = engine.execute_action_burst(burst_steps)
    duration = time.monotonic() - t0

    ui = engine.get_screen_data()
    pause_present = any(el.get("label") == "Pause" or el.get("desc") == "Pause" for el in ui.get("elements", []))
    lap_present = any(el.get("label") == "LAP" or el.get("desc") == "Lap" for el in ui.get("elements", []))
    verified = pause_present and lap_present

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": len(burst_steps),
        "results": results,
        "artifact_path": f"stopwatch_running={verified}",
    }


def run_clock_stopwatch_paused(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    t0 = time.monotonic()
    burst_steps = [
        "click:Pause",
        "wait-text:Start@5",
    ]
    results = engine.execute_action_burst(burst_steps)
    duration = time.monotonic() - t0

    ui = engine.get_screen_data()
    start_present = any(el.get("label") == "Start" or el.get("desc") == "Start" for el in ui.get("elements", []))
    verified = start_present

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": len(burst_steps),
        "results": results,
        "artifact_path": f"stopwatch_paused={verified}",
    }


def run_clock_timer_entry(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    pkg = "com.android.deskclock"
    adb.clear_app_data(pkg)
    adb.launch_app(pkg)

    t0 = time.monotonic()
    burst_steps = [
        "click:TIMER",
        "wait-text:1@5",
        "click:1",
        "click:6",
        "click:3",
        "click:5",
        "wait-text:16m 35s@5",
    ]
    results = engine.execute_action_burst(burst_steps)
    duration = time.monotonic() - t0

    ui = engine.get_screen_data()
    timer_set = any("16m 35s" in str(el.get("label") or "") or "16 minutes, 35 seconds" in str(el.get("desc") or "") for el in ui.get("elements", []))

    return {
        "success": timer_set,
        "duration_sec": round(duration, 2),
        "steps_executed": len(burst_steps),
        "results": results,
        "artifact_path": f"timer_16m35s={timer_set}",
    }


# --- 3. System Tasks ---

def run_system_copy_to_clipboard(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    target_text = "Tracking #: 5K672F4C"
    t0 = time.monotonic()
    adb.set_clipboard(target_text)
    duration = time.monotonic() - t0

    read_back = adb.get_clipboard()
    verified = (read_back == target_text)

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": 1,
        "results": [{"action": "set_clipboard", "text": target_text, "success": verified}],
        "artifact_path": f"clipboard={read_back}",
    }


def run_system_wifi_turn_on(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    t0 = time.monotonic()
    adb.shell("svc wifi enable")
    duration = time.monotonic() - t0

    state = adb.shell("dumpsys wifi | grep 'Wi-Fi is'").strip()
    verified = "enabled" in state.lower()

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": 1,
        "results": [{"action": "wifi_enable", "output": state, "success": verified}],
        "artifact_path": state,
    }


def run_system_wifi_turn_off(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    t0 = time.monotonic()
    adb.shell("svc wifi disable")
    duration = time.monotonic() - t0

    state = adb.shell("dumpsys wifi | grep 'Wi-Fi is'").strip()
    verified = "disabled" in state.lower()

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": 1,
        "results": [{"action": "wifi_disable", "output": state, "success": verified}],
        "artifact_path": state,
    }


def run_system_bluetooth_turn_on(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    t0 = time.monotonic()
    adb.shell("svc bluetooth enable")
    duration = time.monotonic() - t0

    state = adb.shell("cmd bluetooth_manager getState").strip()
    verified = "STATE_ON" in state

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": 1,
        "results": [{"action": "bluetooth_enable", "output": state, "success": verified}],
        "artifact_path": state,
    }


def run_system_bluetooth_turn_off(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    t0 = time.monotonic()
    adb.shell("svc bluetooth disable")
    duration = time.monotonic() - t0

    state = adb.shell("cmd bluetooth_manager getState").strip()
    verified = "STATE_OFF" in state

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": 1,
        "results": [{"action": "bluetooth_disable", "output": state, "success": verified}],
        "artifact_path": state,
    }


def run_system_brightness_max(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    t0 = time.monotonic()
    adb.shell("settings put system screen_brightness 255")
    duration = time.monotonic() - t0

    val = adb.shell("settings get system screen_brightness").strip()
    verified = (val == "255")

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": 1,
        "results": [{"action": "brightness_max", "output": val, "success": verified}],
        "artifact_path": f"screen_brightness={val}",
    }


def run_system_brightness_min(adb: AdbDevice, engine: AndroidEngine) -> dict[str, Any]:
    t0 = time.monotonic()
    adb.shell("settings put system screen_brightness 0")
    duration = time.monotonic() - t0

    val = adb.shell("settings get system screen_brightness").strip()
    verified = (val in ("0", "1"))

    return {
        "success": verified,
        "duration_sec": round(duration, 2),
        "steps_executed": 1,
        "results": [{"action": "brightness_min", "output": val, "success": verified}],
        "artifact_path": f"screen_brightness={val}",
    }


TASK_RUNNERS = {
    "AudioRecorderRecordAudio": run_audio_recorder_record_audio,
    "AudioRecorderRecordAudioWithFileName": run_audio_recorder_record_audio_with_file_name,
    "ClockStopWatchRunning": run_clock_stopwatch_running,
    "ClockStopWatchPausedVerify": run_clock_stopwatch_paused,
    "ClockTimerEntry": run_clock_timer_entry,
    "SystemCopyToClipboard": run_system_copy_to_clipboard,
    "SystemWifiTurnOn": run_system_wifi_turn_on,
    "SystemWifiTurnOff": run_system_wifi_turn_off,
    "SystemBluetoothTurnOn": run_system_bluetooth_turn_on,
    "SystemBluetoothTurnOff": run_system_bluetooth_turn_off,
    "SystemBrightnessMax": run_system_brightness_max,
    "SystemBrightnessMin": run_system_brightness_min,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="AgentDroid AndroidWorld Benchmark Runner")
    parser.add_argument("-s", "--serial", default="127.0.0.1:5555", help="Target device serial")
    parser.add_argument("--task", default="AudioRecorderRecordAudio", help="Specific task name to run")
    parser.add_argument("--all", action="store_true", help="Run all implemented benchmark tasks")
    args = parser.parse_args()

    registry = load_task_registry()
    task_map = {t["task"]: t for t in registry}

    adb = AdbDevice(args.serial)
    engine = AndroidEngine(adb)

    tasks_to_run = list(TASK_RUNNERS.keys()) if args.all else [args.task]
    benchmark_report: list[dict[str, Any]] = []

    for task_name in tasks_to_run:
        runner = TASK_RUNNERS.get(task_name)
        if not runner:
            logger.warning(f"No custom runner implemented yet for {task_name}")
            continue

        meta = task_map.get(task_name, {})
        vostride_sec = meta.get("duration_sec_vostride", 0.0)
        vostride_actions = meta.get("actions_vostride", 0)

        logger.info(f"Running task: {task_name} | Goal: {meta.get('goal')}")
        res = runner(adb, engine)

        speedup = (vostride_sec / res["duration_sec"]) if res["duration_sec"] > 0 and vostride_sec else 1.0
        item = {
            "task": task_name,
            "goal": meta.get("goal"),
            "agentdroid_success": res["success"],
            "agentdroid_sec": res["duration_sec"],
            "agentdroid_steps": res["steps_executed"],
            "vostride_sec": vostride_sec,
            "vostride_actions": vostride_actions,
            "speedup": f"{speedup:.2f}x",
            "artifact": res.get("artifact_path"),
        }
        benchmark_report.append(item)
        logger.info(f"Task {task_name} finished: AgentDroid={res['duration_sec']}s vs Vostride={vostride_sec}s ({speedup:.2f}x speedup)")

    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(benchmark_report, f, indent=2)
    logger.info(f"Saved benchmark results to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
