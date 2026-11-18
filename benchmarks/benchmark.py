#!/usr/bin/env python3
"""Unified AgentDroid Benchmark Suite.

Single source of truth for reproducing all published AgentDroid metrics on live hardware:
  1. Runtime & Perception Micro-Benchmarks: container cold start, APK install, kernel
     InputDaemon tap vs ADB input, UI dump turnaround vs screenshot, burst vs shell chain,
     and screen payload / vision token efficiency (Mobilebox summary.csv + AndroidWorld M3A parity).
  2. Verifiable 13-Task E2E Suite: complexity-stratified (Simple / Medium / Complex) tasks
     across 8 real open-source Android apps graded by independent post-condition verifiers
     (SQLite, ContentProvider, /sdcard/ disk files, UI state deltas) across Compound
     (1-turn host burst) and optional TypeSafe AI Jev (`jev-latest`) autonomous loop modes.

Usage:
    python3 benchmarks/benchmark.py [--serial 127.0.0.1:5555] [--cold-starts 3] [--with-jev]
"""

from __future__ import annotations

import argparse
import base64
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agentdroid.adb import AdbDevice, probe_adbd_tcp
from agentdroid.engine import AndroidEngine
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.typesafe_ai import TypeSafeAIClient

CACHE_DIR = Path.home() / ".cache" / "agentdroid" / "apks"
FOSSIFY_APK = CACHE_DIR / "org.fossify.math_10.apk"
RESULTS_PATH = REPO_ROOT / "benchmarks" / "results" / "summary.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("agentdroid.benchmark")


# ---------------------------------------------------------------------------
# Statistics & Runtime Infrastructure Micro-Benchmarks
# ---------------------------------------------------------------------------


def summarize(samples: list[float]) -> dict[str, Any]:
    ordered = sorted(samples)
    n = len(ordered)
    p90_idx = min(n - 1, max(0, math.ceil(0.9 * n) - 1))
    return {
        "n": n,
        "median_ms": round(statistics.median(ordered), 2),
        "mean_ms": round(statistics.mean(ordered), 2),
        "min_ms": round(ordered[0], 2),
        "p90_ms": round(ordered[p90_idx], 2),
        "max_ms": round(ordered[-1], 2),
    }


def wait_helper_ready(dev: AdbDevice, timeout: float = 25.0) -> AccessibilityHelperClient:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        helper = AccessibilityHelperClient(dev)
        if helper.ensure_ready():
            return helper
        time.sleep(0.5)
    raise RuntimeError(f"AccessibilityHelperClient not ready within {timeout}s")


def measure_container_cold_starts(serial: str, container_name: str, runs: int) -> dict[str, Any]:
    if runs <= 0:
        return {"skipped": True}

    ready_samples: list[float] = []
    screenshot_samples: list[float] = []
    tmp_shot = Path("/tmp/agentdroid_cold_start_bench.png")
    host, _, port_s = serial.rpartition(":")

    for i in range(runs):
        tmp_shot.unlink(missing_ok=True)
        t0 = time.perf_counter()
        proc = subprocess.run(["docker", "restart", container_name], capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"docker restart {container_name} failed: {proc.stderr.strip()}")
        subprocess.run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=3)

        while True:
            if time.perf_counter() - t0 > 120:
                raise TimeoutError(f"Container {container_name} did not boot within 120s")
            try:
                if host and port_s.isdigit() and not probe_adbd_tcp(host, int(port_s), timeout=0.35):
                    time.sleep(0.15)
                    continue
                subprocess.run(["adb", "connect", serial], capture_output=True, text=True, timeout=4)
                probe = subprocess.run(
                    ["adb", "-s", serial, "shell", 'if [ "$(getprop sys.boot_completed)" = "1" ]; then echo BOOT=1; pm path android; fi'],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if probe.returncode == 0 and "BOOT=1" in probe.stdout and "package:" in probe.stdout:
                    break
                if probe.returncode != 0:
                    subprocess.run(["adb", "disconnect", serial], capture_output=True, text=True, timeout=2)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.15)

        ready_ms = (time.perf_counter() - t0) * 1000.0
        ready_samples.append(ready_ms)

        shot_proc = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"], capture_output=True, timeout=20)
        if shot_proc.returncode != 0 or len(shot_proc.stdout) <= 1000:
            raise RuntimeError("screencap failed after cold restart")
        tmp_shot.write_bytes(shot_proc.stdout)
        cold_to_screen_ms = (time.perf_counter() - t0) * 1000.0
        screenshot_samples.append(cold_to_screen_ms)

        dev = AdbDevice(serial=serial)
        dev.connect(timeout=5.0)
        wait_helper_ready(dev, timeout=25.0)
        logger.info(f"  [cold_start {i + 1}/{runs}] ready={ready_ms:.1f}ms cold_start_to_screenshot={cold_to_screen_ms:.1f}ms")

    return {"container": container_name, "ready": summarize(ready_samples), "cold_start_to_screenshot": summarize(screenshot_samples)}


def compute_vision_tokens(width: int, height: int) -> dict[str, Any]:
    long_side = max(width, height)
    scale = min(2048.0 / long_side, 1.0)
    w_s, h_s = width * scale, height * scale
    if min(w_s, h_s) > 768.0:
        s2 = 768.0 / min(w_s, h_s)
        w_s, h_s = w_s * s2, h_s * s2
    openai_tokens = 85 + 170 * (math.ceil(w_s / 512.0) * math.ceil(h_s / 512.0))
    a_scale = min(1568.0 / long_side, 1.0)
    anthropic_tokens = math.ceil((round(width * a_scale) * round(height * a_scale)) / 750.0)
    return {"openai_high_detail_tokens": openai_tokens, "anthropic_vision_tokens": anthropic_tokens}


def measure_runtime_and_payloads(serial: str, container: str, cold_starts: int) -> dict[str, Any]:
    dev = AdbDevice(serial=serial)
    if not dev.connect(timeout=5.0):
        raise RuntimeError(f"Cannot connect to ADB device {serial}")
    helper = wait_helper_ready(dev, timeout=25.0)
    helper._ensure_input_daemon(force=False)
    engine = AndroidEngine(adb=dev)

    logger.info("=== Phase 1: Runtime & Perception Micro-Benchmarks ===")
    cold_res = measure_container_cold_starts(serial, container, cold_starts)
    if cold_starts > 0:
        dev = AdbDevice(serial=serial)
        dev.connect(timeout=5.0)
        dev.ensure_root()
        helper = wait_helper_ready(dev, timeout=25.0)
        helper._ensure_input_daemon(force=False)
        engine = AndroidEngine(adb=dev)

    apk_res: dict[str, Any] = {}
    if FOSSIFY_APK.exists():
        fresh, reinstall = [], []
        for _ in range(3):
            dev.shell("pm uninstall org.fossify.math")
            t0 = time.perf_counter()
            proc = dev.run_adb(["install", "-g", str(FOSSIFY_APK)], timeout=120)
            if proc.returncode != 0 or "Success" not in proc.stdout:
                raise RuntimeError(f"Fresh APK install failed: {proc.stdout} {proc.stderr}")
            fresh.append((time.perf_counter() - t0) * 1000.0)
        for _ in range(5):
            t0 = time.perf_counter()
            proc = dev.run_adb(["install", "-r", "-t", "-g", str(FOSSIFY_APK)], timeout=120)
            if proc.returncode != 0 or "Success" not in proc.stdout:
                raise RuntimeError(f"Reinstall APK failed: {proc.stdout} {proc.stderr}")
            reinstall.append((time.perf_counter() - t0) * 1000.0)
        apk_res = {
            "fossify_math_bytes": FOSSIFY_APK.stat().st_size,
            "fresh_install": summarize(fresh),
            "reinstall": summarize(reinstall),
        }

    def _time_n(fn: Callable[[], Any], n: int) -> list[float]:
        out = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            out.append((time.perf_counter() - t0) * 1000.0)
        return out

    dev.launch_app("org.fossify.math")
    time.sleep(0.8)
    tmp_png = "/tmp/agentdroid_tap_shot_bench.png"

    micro = {
        "helper_action_tap": summarize(_time_n(lambda: helper.action("tap", x=540, y=1200), 10)),
        "adb_input_tap": summarize(_time_n(lambda: dev.shell("input tap 540 1200"), 20)),
        "artemis_ui_dump": summarize(_time_n(lambda: helper.dump_compact_ui(max_elements=80), 20)),
        "tap_to_ui_dump": summarize(_time_n(lambda: (helper.action("tap", x=540, y=1200), helper.dump_compact_ui(max_elements=80)), 10)),
        "tap_to_screenshot_adb": summarize(_time_n(lambda: (dev.shell("input tap 540 1200"), dev.screenshot(tmp_png)), 10)),
        "compound_burst_3_actions": summarize(_time_n(lambda: engine.execute_action_burst(["key:HOME", "tap:540,1200", "key:BACK"]), 5)),
        "adb_shell_chain_3_actions": summarize(_time_n(lambda: dev.shell("input keyevent HOME && input tap 540 1200 && input keyevent BACK"), 5)),
    }

    payloads: dict[str, Any] = {}
    for label, pkg in (("fossify_math", "org.fossify.math"), ("android_settings", "com.android.settings")):
        dev.shell(f"am force-stop {pkg}")
        dev.launch_app(pkg)
        time.sleep(1.0)
        snap = helper._request("GET", "/snapshot?fields=xml")
        if not snap.get("has_screenshot"):
            time.sleep(1.0)
            snap = helper._request("GET", "/snapshot?fields=xml")
        xml_str = snap.get("xml", "")
        png_bytes = base64.b64decode(snap.get("screenshot_base64", "") or b"")
        formatted = engine.get_screen_data(max_elements=80).get("formatted_text", "")
        payloads[label] = {
            "raw_xml_bytes": len(xml_str.encode("utf-8")),
            "raw_xml_est_tokens": math.ceil(len(xml_str) / 4),
            "formatted_text_chars": len(formatted),
            "formatted_text_est_tokens": math.ceil(len(formatted) / 4),
            "screenshot_png_bytes": len(png_bytes),
            **compute_vision_tokens(int(snap.get("width") or 1080), int(snap.get("height") or 2400)),
        }

    logger.info(
        f"  Tap: {micro['helper_action_tap']['median_ms']}ms vs adb {micro['adb_input_tap']['median_ms']}ms | "
        f"UI loop: {micro['tap_to_ui_dump']['median_ms']}ms vs screencap {micro['tap_to_screenshot_adb']['median_ms']}ms"
    )
    return {
        "container_cold_restart": cold_res,
        "apk_operations": apk_res,
        "micro_benchmarks": micro,
        "perception_payloads": payloads,
    }


# ---------------------------------------------------------------------------
# Verifiable 13-Task E2E Suite
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    app_name: str
    package: str
    tier: str
    goal: str
    max_steps: int
    compound_steps: list[str]
    setup_fn: Callable[[AdbDevice, AndroidEngine, AccessibilityHelperClient], dict[str, Any]]
    verify_fn: Callable[[AdbDevice, AndroidEngine, AccessibilityHelperClient, dict[str, Any]], tuple[bool, str]]
    baseline_source: str | None = None
    baseline_sec: float | None = None
    baseline_actions: int | None = None
    cleanup_fn: Callable[[AdbDevice], None] | None = None
    min_steps_before_done: int = 1


def _setup_clean_launch(pkg: str, *, grant: bool = False, settle: float = 0.8) -> Callable[..., dict[str, Any]]:
    def _setup(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
        adb.stop_app(pkg)
        adb.clear_app_data(pkg)
        if grant:
            adb.grant_all_permissions(pkg)
        adb.launch_app(pkg, wait=True)
        time.sleep(settle)
        return {}

    return _setup


def _setup_stopwatch_running(adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.clear_app_data("com.android.deskclock")
    adb.launch_app("com.android.deskclock", wait=True)
    eng.execute_action_burst(["wait-text:STOPWATCH@5", "click:STOPWATCH", "wait-text:START@5", "click:START", "sleep:0.6"])
    return {}


def _verify_stopwatch_running(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    labels = {str(el.get("label") or el.get("desc") or "").strip().lower() for el in eng.get_screen_data(max_elements=40).get("elements") or []}
    return ("pause" in labels and "lap" in labels), f"pause={'pause' in labels}, lap={'lap' in labels}"


def _verify_stopwatch_paused(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    labels = {str(el.get("label") or el.get("desc") or "").strip().lower() for el in eng.get_screen_data(max_elements=40).get("elements") or []}
    return ("start" in labels and "pause" not in labels), f"start={'start' in labels}, pause_absent={'pause' not in labels}"


def _verify_about_phone(adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    fg = adb.foreground_app()
    txt = eng.get_screen_data(max_elements=80).get("formatted_text", "")
    ok = fg.get("package") == "com.android.settings" and "Android version" in txt and "Device name" in txt
    return ok, f"pkg={fg.get('package')}, android_version={'Android version' in txt}"


def _count_alarms(helper: AccessibilityHelperClient) -> tuple[int, int]:
    els = helper.dump_compact_ui(max_elements=80).get("elements") or []
    return (
        sum(1 for e in els if e.get("resource_id") == "digital_clock"),
        sum(1 for e in els if e.get("resource_id") == "onoff" and e.get("label") == "ON"),
    )


def _setup_alarm(adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.clear_app_data("com.android.deskclock")
    adb.launch_app("com.android.deskclock", wait=True)
    eng.execute_action_burst(["wait-text:Alarm@5", "click:Alarm", "sleep:0.4"])
    clocks, on_sw = _count_alarms(helper)
    return {"before_clocks": clocks, "before_on": on_sw}


def _verify_alarm(_adb: AdbDevice, _eng: AndroidEngine, helper: AccessibilityHelperClient, ctx: dict[str, Any]) -> tuple[bool, str]:
    clocks, on_sw = _count_alarms(helper)
    ok = clocks == ctx["before_clocks"] + 1 and on_sw == ctx["before_on"] + 1
    return ok, f"clocks={ctx['before_clocks']}->{clocks}, on={ctx['before_on']}->{on_sw}"


def _verify_timer(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    blob = " | ".join(f"{e.get('label', '')} {e.get('desc', '')}" for e in eng.get_screen_data(max_elements=50).get("elements") or [])
    ok = "16m 35s" in blob or "16 minutes, 35 seconds" in blob
    return ok, f"timer_16m35s={ok}"


def _verify_tasks(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE deleted = 0;\" 2>/dev/null").strip()
    return ("Submit benchmark report" in out), f"sqlite={out!r}"


def _verify_math(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    el = next((e for e in eng.get_screen_data(max_elements=40).get("elements") or [] if e.get("resource_id") == "result"), None)
    val = str(el.get("label")) if el else ""
    return val == "100", f"result={val!r}"


def _setup_audio(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    pkg = "com.dimowner.audiorecorder"
    adb.clear_app_data(pkg)
    adb.grant_all_permissions(pkg)
    adb.shell("rm -rf /sdcard/Android/data/com.dimowner.audiorecorder/files/* /sdcard/Records/* /sdcard/Music/records/* 2>/dev/null || true")
    adb.launch_app(pkg, wait=True)
    time.sleep(0.8)
    return {}


def _verify_audio(prefix: str) -> Callable[..., tuple[bool, str]]:
    def _verify(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
        out = adb.shell(f"find /sdcard/ -name '{prefix}*.m4a' -exec ls -l {{}} + 2>/dev/null").strip()
        if not out:
            return False, f"no '{prefix}*.m4a' on /sdcard"
        parts = out.splitlines()[0].split()
        size = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        return size > 1000, f"file={parts[-1]}, bytes={size}"

    return _verify


def _verify_contacts(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("content query --uri content://com.android.contacts/data --projection display_name:data1 2>/dev/null").strip()
    ok = "Ada" in out and ("555-0199" in out or "5550199" in out)
    return ok, f"matched_ada_5550199={ok}"


def _verify_calendar(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title, location FROM events;\" 2>/dev/null").strip()
    return ("Architecture Sync" in out and "Room 402" in out), f"sqlite={out!r}"


def _verify_broccoli(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"SELECT title, preparationTime, ingredients FROM recipes;\" 2>/dev/null").strip()
    return ("Pasta Pesto" in out and "15 mins" in out and "Pasta, Basil, Garlic" in out), f"sqlite={out!r}"


def _setup_markor(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.shell("rm -rf /sdcard/Documents/markor/bench_log* /sdcard/Documents/markor/2026-* /sdcard/Documents/bench_log* 2>/dev/null || true")
    adb.clear_app_data("net.gsantner.markor")
    adb.grant_all_permissions("net.gsantner.markor")
    adb.launch_app("net.gsantner.markor", wait=True)
    time.sleep(0.8)
    return {}


def _verify_markor(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    path_out = adb.shell("find /sdcard/Documents -name 'bench_log*.md' 2>/dev/null | head -n 1").strip()
    if not path_out:
        return False, "bench_log.md missing"
    local_tmp = Path("/tmp/agentdroid_verify_bench_log.md")
    local_tmp.unlink(missing_ok=True)
    adb.pull_file(path_out, str(local_tmp))
    text = local_tmp.read_text(encoding="utf-8", errors="replace") if local_tmp.exists() else ""
    ok = "Verified on Redroid" in text
    return ok, f"remote={path_out}, bytes={len(text.encode('utf-8'))}, match={ok}"


TASKS: list[TaskSpec] = [
    TaskSpec(
        "ClockStopWatchRunning", "Clock", "com.android.deskclock", "Simple",
        "Switch to the STOPWATCH tab and tap START to start the stopwatch.", 8,
        ["wait-text:STOPWATCH@5", "click:STOPWATCH", "wait-text:START@5", "click:START", "wait-text:Pause@5"],
        _setup_clean_launch("com.android.deskclock"), _verify_stopwatch_running,
        "Vostride / AndroidWorld", 38.0, 2, min_steps_before_done=2,
    ),
    TaskSpec(
        "ClockStopWatchPausedVerify", "Clock", "com.android.deskclock", "Simple",
        "Tap Pause to pause the running stopwatch.", 8,
        ["click:Pause", "wait-text:Start@5"],
        _setup_stopwatch_running, _verify_stopwatch_paused,
        "Vostride / AndroidWorld", 97.0, 4, min_steps_before_done=1,
    ),
    TaskSpec(
        "SettingsNavigateAboutPhone", "Settings", "com.android.settings", "Simple",
        "Scroll down Settings and open 'About phone' so Android version and Device name are visible.", 8,
        ["scroll-to:About phone", "click:About phone", "wait-text:Android version@5"],
        _setup_clean_launch("com.android.settings"), _verify_about_phone, min_steps_before_done=2,
    ),
    TaskSpec(
        "DeskClockAddAlarm", "Clock", "com.android.deskclock", "Medium",
        "Tap Add alarm (+) and confirm OK to create and enable a new alarm.", 10,
        ["wait-text:Add alarm@5", "click:Add alarm", "wait-text:OK@5", "click:OK", "sleep:0.4"],
        _setup_alarm, _verify_alarm, cleanup_fn=lambda adb: adb.clear_app_data("com.android.deskclock"), min_steps_before_done=2,
    ),
    TaskSpec(
        "ClockTimerEntry", "Clock", "com.android.deskclock", "Medium",
        "Switch to the TIMER tab and enter digits 1, 6, 3, 5 in order so the display shows 16m 35s. Do not start the timer.", 12,
        ["wait-text:TIMER@5", "click:TIMER", "sleep:0.3", "wait-text:timer_setup_digit_1@5", "click:1", "click:6", "click:3", "click:5", "wait-text:16m 35s@5"],
        _setup_clean_launch("com.android.deskclock"), _verify_timer,
        "Vostride / AndroidWorld", 57.0, 6, min_steps_before_done=5,
    ),
    TaskSpec(
        "TasksAddTask", "Tasks", "org.tasks", "Medium",
        "Tap Create new task, fill the title with 'Submit benchmark report', and tap Save.", 10,
        ["wait-text:Create new task@5", "click:Create new task", "wait-text:title@5", "fill:title=Submit benchmark report", "hide-keyboard", "click:Save", "wait-text:Submit benchmark report@5"],
        _setup_clean_launch("org.tasks", grant=True), _verify_tasks,
        "AndroidWorld App", min_steps_before_done=3,
    ),
    TaskSpec(
        "FossifyMathCompute", "Fossify Math", "org.fossify.math", "Medium",
        "Press calculator buttons '4', '2', '+', '5', '8', '=' in exact order to compute 42 + 58 = 100.", 14,
        ["wait-text:btn_4@5", "click:btn_4", "click:btn_2", "click:btn_plus", "click:btn_5", "click:btn_8", "click:btn_equals", "wait-text:100@5"],
        _setup_clean_launch("org.fossify.math"), _verify_math,
        "Mobilebox parity APK", min_steps_before_done=6,
    ),
    TaskSpec(
        "AudioRecorderRecordAudio", "Audio Recorder", "com.dimowner.audiorecorder", "Medium",
        "Complete onboarding if shown (Get started, Apply), tap record to start recording, wait 1.5s once, stop recording, and tap Save.", 14,
        ["wait-any:Get started|Apply|Recording: %s@5", "if-visible:Get started->click:Get started", "wait-any:Apply|Recording: %s@5", "if-visible:Apply->click:Apply", "wait-text:Recording: %s@5", "click:Recording: %s", "sleep:1.5", "click:btn_record_stop", "wait-text:Save@5", "click:Save", "sleep:0.6"],
        _setup_audio, _verify_audio("Record-1"),
        "Vostride / AndroidWorld", 62.0, 6, min_steps_before_done=5,
    ),
    TaskSpec(
        "ContactsAddContact", "Contacts", "com.android.contacts", "Complex",
        "Create a new contact with name 'Ada' and phone number '5550199', and save it.", 14,
        ["wait-text:Create new contact@5", "click:Create new contact", "sleep:0.4", "if-visible:CANCEL->click:CANCEL", "wait-text:SAVE@5", "fill:EditText=Ada", "hide-keyboard", "tap:556,1297", "type:5550199", "hide-keyboard", "click:SAVE", "sleep:0.4"],
        _setup_clean_launch("com.android.contacts", grant=True), _verify_contacts,
        "Vostride / AndroidWorld", 81.0, 7, min_steps_before_done=4,
    ),
    TaskSpec(
        "SimpleCalendarAddOneEvent", "Simple Calendar", "com.simplemobiletools.calendar.pro", "Complex",
        "Tap New Event to create a calendar event, enter title 'Architecture Sync' and location 'Room 402', and tap Save.", 14,
        ["wait-text:New Event@5", "click:New Event", "sleep:0.3", "if-visible:Event->click:Event", "wait-text:event_title@5", "fill:event_title=Architecture Sync", "hide-keyboard", "fill:event_location=Room 402", "hide-keyboard", "click:Save", "sleep:0.3", "if-visible:OK->click:OK", "sleep:0.3"],
        _setup_clean_launch("com.simplemobiletools.calendar.pro", grant=True), _verify_calendar,
        "Vostride / AndroidWorld", 184.0, 18, min_steps_before_done=4,
    ),
    TaskSpec(
        "BroccoliAddSingleRecipe", "Broccoli", "com.flauschcode.broccoli", "Complex",
        "Add a new recipe titled 'Pasta Pesto' with preparation time '15 mins' and ingredients 'Pasta, Basil, Garlic', then tap SAVE.", 14,
        ["wait-text:New Recipe@5", "click:New Recipe", "wait-text:new_title@5", "fill:new_title=Pasta Pesto", "hide-keyboard", "fill:new_preparation_time=15 mins", "hide-keyboard", "fill:new_ingredients=Pasta, Basil, Garlic", "hide-keyboard", "click:SAVE", "sleep:0.4"],
        _setup_clean_launch("com.flauschcode.broccoli", grant=True), _verify_broccoli,
        "Vostride / AndroidWorld", 138.0, 13, min_steps_before_done=5,
    ),
    TaskSpec(
        "AudioRecorderRecordAudioWithFileName", "Audio Recorder", "com.dimowner.audiorecorder", "Complex",
        "Complete onboarding if shown (Get started, Apply), tap record to start recording, wait 1.5s once, stop recording, type 'interview_clip' as filename, and tap Save.", 16,
        ["wait-any:Get started|Apply|Recording: %s@5", "if-visible:Get started->click:Get started", "wait-any:Apply|Recording: %s@5", "if-visible:Apply->click:Apply", "wait-text:Recording: %s@5", "click:Recording: %s", "sleep:1.5", "click:btn_record_stop", "wait-text:input_name@5", "fill:input_name=interview_clip", "hide-keyboard", "click:Save", "sleep:0.6"],
        _setup_audio, _verify_audio("interview_clip"),
        "Vostride / AndroidWorld", 106.0, 10, min_steps_before_done=6,
    ),
    TaskSpec(
        "MarkorCreateAndSaveNote", "Markor", "net.gsantner.markor", "Complex",
        "Pass onboarding (NEXT/DONE/OK), tap create new file, fill file Name with 'bench_log' then tap OK, write 'Verified on Redroid' in the note editor, and tap Save.", 18,
        ["wait-text:NEXT@5", "click:NEXT", "sleep:0.25", "click:NEXT", "sleep:0.25", "click:NEXT", "sleep:0.25", "click:NEXT", "sleep:0.25", "click:DONE", "wait-text:OK@5", "click:OK", "wait-text:Create a new file or folder@5", "click:Create a new file or folder", "wait-text:new_file_dialog__name@5", "fill:new_file_dialog__name=bench_log", "hide-keyboard", "click:OK", "wait-text:document__fragment__edit__highlighting_editor@5", "fill:document__fragment__edit__highlighting_editor=Verified on Redroid", "sleep:0.3", "hide-keyboard", "sleep:0.3", "click:action_save", "sleep:0.5", "key:BACK", "sleep:0.5"],
        _setup_markor, _verify_markor,
        "Vostride / AndroidWorld (+onboarding)", 64.0, 6, min_steps_before_done=9,
    ),
]


def run_compound_task(task: TaskSpec, adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.clear_logs()
    ctx = task.setup_fn(adb, eng, helper)
    t0 = time.perf_counter()
    eng.execute_action_burst(task.compound_steps)
    wall_sec = round(time.perf_counter() - t0, 3)

    passed, evidence = task.verify_fn(adb, eng, helper, ctx)
    crashes = adb.collect_crashes(task.package)
    if task.cleanup_fn:
        task.cleanup_fn(adb)
    else:
        adb.stop_app(task.package)

    return {
        "task_id": task.task_id,
        "app": task.app_name,
        "tier": task.tier,
        "ok": bool(passed and not crashes.has_crashes),
        "wall_clock_sec": wall_sec,
        "steps_executed": len(task.compound_steps),
        "verification": evidence,
        "baseline_sec": task.baseline_sec,
    }


def run_jev_task(task: TaskSpec, adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient, client: TypeSafeAIClient) -> dict[str, Any]:
    adb.clear_logs()
    ctx = task.setup_fn(adb, eng, helper)
    step_history: list[str] = []
    latencies: list[float] = []
    payload_chars = 0
    terminated = "max_steps"
    steps = 0

    t0 = time.perf_counter()
    for step in range(1, task.max_steps + 1):
        ui = eng.get_screen_data(max_elements=80)
        payload_chars += len(ui.get("formatted_text", ""))
        try:
            d = client.rank_next_action(ui, task.goal, step_history=step_history)
        except Exception as exc:
            terminated = f"api_error:{type(exc).__name__}"
            break

        steps = step
        latencies.append(float(d.get("latency_ms", 0.0)))
        act_key = d.get("action_key", "wait")
        act_type = d.get("action_type", act_key)
        act_label = d.get("action_label", act_key)

        if act_key == "done":
            terminated = "agent_done"
            break

        m = d.get("matched_element")
        if act_type == "fill" and m and d.get("fill_text") is not None:
            cx, cy = m["center"]
            eng.tap(float(cx), float(cy))
            time.sleep(0.2)
            eng.execute_action({"type": "type", "text": str(d["fill_text"])})
            eng.execute_action({"type": "hide_keyboard"})
            time.sleep(0.35)
        elif act_type == "tap" and m:
            cx, cy = m["center"]
            eng.tap(float(cx), float(cy))
            time.sleep(0.45)
        elif act_type in ("scroll_down", "scroll_up"):
            eng.execute_action({"type": "scroll", "direction": "down" if act_type == "scroll_down" else "up"})
            time.sleep(0.45)
        elif act_type == "back":
            helper.action("global", action="BACK")
            time.sleep(0.45)
        elif act_type == "wait":
            time.sleep(1.5)
        else:
            time.sleep(0.4)

        step_history.append(f"Step {step}: {act_label}")
        if d.get("is_goal_met") and step >= task.min_steps_before_done:
            terminated = "goal_met_noul"
            break

    wall_sec = round(time.perf_counter() - t0, 3)
    passed, evidence = task.verify_fn(adb, eng, helper, ctx)
    crashes = adb.collect_crashes(task.package)
    if task.cleanup_fn:
        task.cleanup_fn(adb)
    else:
        adb.stop_app(task.package)

    return {
        "task_id": task.task_id,
        "app": task.app_name,
        "tier": task.tier,
        "ok": bool(passed and not crashes.has_crashes),
        "wall_clock_sec": wall_sec,
        "steps_executed": steps,
        "terminated_reason": terminated,
        "mean_ai_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "total_prompt_est_tokens": math.ceil(payload_chars / 4),
        "verification": evidence,
        "baseline_sec": task.baseline_sec,
    }


def summarize_track(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_tier: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for r in rows:
        by_tier[r["tier"]].append(r)

    def _agg(items: list[dict[str, Any]]) -> dict[str, Any]:
        n = len(items)
        passed = sum(1 for x in items if x["ok"])
        return {
            "total": n,
            "passed": passed,
            "success_rate_pct": round((passed / n) * 100.0, 1) if n else 0.0,
            "mean_wall_sec": round(statistics.mean(x["wall_clock_sec"] for x in items), 2) if n else 0.0,
            "total_wall_sec": round(sum(x["wall_clock_sec"] for x in items), 2),
            "mean_steps": round(statistics.mean(x["steps_executed"] for x in items), 2) if n else 0.0,
        }

    return {"overall": _agg(rows), "by_tier": {t: _agg(by_tier[t]) for t in ("Simple", "Medium", "Complex") if by_tier[t]}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run unified AgentDroid benchmark suite.")
    parser.add_argument("-s", "--serial", default="127.0.0.1:5555")
    parser.add_argument("--container", default="agentdroid-device")
    parser.add_argument("--cold-starts", type=int, default=3)
    parser.add_argument("--with-jev", action="store_true", help="Also run live TypeSafe AI (Jev) autonomous track.")
    parser.add_argument("--skip-infra", action="store_true")
    parser.add_argument("--api-key", default=os.environ.get("TYPESAFE_API_KEY", ""))
    parser.add_argument("--output", default=str(RESULTS_PATH))
    args = parser.parse_args()

    out_path = Path(args.output)
    existing: dict[str, Any] = {}
    if out_path.exists():
        try:
            existing = json.loads(out_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    adb = AdbDevice(serial=args.serial)
    if not adb.connect(timeout=10.0):
        raise RuntimeError(f"Cannot connect to ADB device {args.serial}")
    adb.ensure_root()

    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "device_serial": args.serial,
        "device_model": adb.shell("getprop ro.product.model").strip(),
        "android_release": adb.shell("getprop ro.build.version.release").strip(),
        "runtime": existing.get("runtime", {}),
        "e2e_modes": dict(existing.get("e2e_modes", {})),
    }

    if not args.skip_infra:
        report["runtime"] = measure_runtime_and_payloads(args.serial, args.container, args.cold_starts)
        adb.connect(timeout=10.0)
        adb.ensure_root()

    helper = wait_helper_ready(adb, timeout=25.0)
    helper._ensure_input_daemon(force=False)
    eng = AndroidEngine(adb=adb)

    logger.info("=== Phase 2: 13-Task Verifiable E2E Suite (Compound 1-Turn Mode) ===")
    comp_rows = []
    for idx, task in enumerate(TASKS, 1):
        row = run_compound_task(task, adb, eng, helper)
        comp_rows.append(row)
        logger.info(f"  [{idx}/13] {task.tier:7s} | {task.task_id:37s} | {'PASS' if row['ok'] else 'FAIL'} | {row['wall_clock_sec']:5.2f}s | {row['steps_executed']:2d} steps | {row['verification']}")
        if idx % 4 == 0:
            adb.trim_background_apps()
    report["e2e_modes"]["compound"] = {"summary": summarize_track(comp_rows), "tasks": comp_rows}

    if args.with_jev:
        if not args.api_key:
            raise ValueError("TYPESAFE_API_KEY env var or --api-key is required with --with-jev")
        client = TypeSafeAIClient(api_key=args.api_key)
        client.is_valid()
        logger.info("=== Phase 3: 13-Task Verifiable E2E Suite (Autonomous Jev System One Mode) ===")
        jev_rows = []
        for idx, task in enumerate(TASKS, 1):
            row = run_jev_task(task, adb, eng, helper, client)
            jev_rows.append(row)
            logger.info(f"  [{idx}/13] {task.tier:7s} | {task.task_id:37s} | {'PASS' if row['ok'] else 'FAIL'} | {row['wall_clock_sec']:5.2f}s | {row['steps_executed']:2d} steps | ai={row['mean_ai_latency_ms']:5.1f}ms | {row['terminated_reason']}")
            if idx % 4 == 0:
                adb.trim_background_apps()
        client.close()
        report["e2e_modes"]["jev"] = {"summary": summarize_track(jev_rows), "tasks": jev_rows}

    adb.trim_background_apps()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    logger.info(f"Saved unified benchmark summary to {out_path}")


if __name__ == "__main__":
    main()
