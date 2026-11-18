#!/usr/bin/env python3
"""Verifiable End-to-End AndroidWorld & Real-App Benchmark Suite for AgentDroid.

Evaluates complexity-stratified tasks (Simple, Medium, Complex) across 8 real Android
applications on live hardware using strict, independent ground-truth post-condition
verifiers (filesystem, SQLite databases, Android ContentProviders, and UI state deltas).

Supports two execution modes:
  1. `jev`: Autonomous closed-loop decision agent (AgentDroid + TypeSafe AI `jev-latest`)
     running dynamically until `done`/`is_goal_met` or `max_steps` (never truncated prematurely).
  2. `compound`: Single-turn compound burst (`AndroidEngine.execute_action_burst`),
     modeling host coding agents (Claude / Gemini / Codex) planning once via AgentDroid MCP/CLI.

Usage:
    export TYPESAFE_API_KEY="..."
    python3 benchmarks/run_e2e_benchmark.py [--serial 127.0.0.1:5555] [--mode both]
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.typesafe_ai import TypeSafeAIClient

RESULTS_PATH = REPO_ROOT / "benchmarks" / "results" / "benchmark_e2e_results.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("e2e_benchmark")


@dataclass(frozen=True)
class TaskSpec:
    """Definition of a verifiable end-to-end Android benchmark task."""

    task_id: str
    app_name: str
    package: str
    tier: str  # Simple | Medium | Complex
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


# ---------------------------------------------------------------------------
# Precondition Setup & Independent Ground-Truth Verifiers
# ---------------------------------------------------------------------------


def _setup_clean_launch(pkg: str, *, clear: bool = True, grant: bool = False, settle: float = 0.8) -> Callable[..., dict[str, Any]]:
    def _setup(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
        adb.stop_app(pkg)
        if clear:
            adb.clear_app_data(pkg)
        if grant:
            adb.grant_all_permissions(pkg)
        adb.launch_app(pkg, wait=True)
        time.sleep(settle)
        return {}

    return _setup


def _setup_stopwatch_running(adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    pkg = "com.android.deskclock"
    adb.clear_app_data(pkg)
    adb.launch_app(pkg, wait=True)
    eng.execute_action_burst(["wait-text:STOPWATCH@5", "click:STOPWATCH", "wait-text:START@5", "click:START", "sleep:0.6"])
    return {}


def _verify_stopwatch_running(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    ui = eng.get_screen_data(max_elements=40)
    labels = {str(el.get("label") or el.get("desc") or "").strip().lower() for el in ui.get("elements") or []}
    ok = "pause" in labels and "lap" in labels
    return ok, f"pause_present={'pause' in labels}, lap_present={'lap' in labels}"


def _verify_stopwatch_paused(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    ui = eng.get_screen_data(max_elements=40)
    labels = {str(el.get("label") or el.get("desc") or "").strip().lower() for el in ui.get("elements") or []}
    ok = "start" in labels and "pause" not in labels
    return ok, f"start_present={'start' in labels}, pause_absent={'pause' not in labels}"


def _verify_about_phone(adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    fg = adb.foreground_app()
    txt = eng.get_screen_data(max_elements=80).get("formatted_text", "")
    has_ver = "Android version" in txt
    has_name = "Device name" in txt
    ok = fg.get("package") == "com.android.settings" and has_ver and has_name
    return ok, f"pkg={fg.get('package')}, android_version={has_ver}, device_name={has_name}"


def _count_deskclock_alarms(helper: AccessibilityHelperClient) -> tuple[int, int]:
    elements = helper.dump_compact_ui(max_elements=80).get("elements") or []
    clocks = [e for e in elements if e.get("resource_id") == "digital_clock"]
    on_sw = [e for e in elements if e.get("resource_id") == "onoff" and e.get("label") == "ON"]
    return len(clocks), len(on_sw)


def _setup_deskclock_alarm(adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient) -> dict[str, Any]:
    adb.clear_app_data("com.android.deskclock")
    adb.launch_app("com.android.deskclock", wait=True)
    eng.execute_action_burst(["wait-text:Alarm@5", "click:Alarm", "sleep:0.4"])
    before_clocks, before_on = _count_deskclock_alarms(helper)
    return {"before_clocks": before_clocks, "before_on": before_on}


def _verify_deskclock_alarm(_adb: AdbDevice, _eng: AndroidEngine, helper: AccessibilityHelperClient, ctx: dict[str, Any]) -> tuple[bool, str]:
    after_clocks, after_on = _count_deskclock_alarms(helper)
    ok = after_clocks == ctx["before_clocks"] + 1 and after_on == ctx["before_on"] + 1
    return ok, f"clocks={ctx['before_clocks']}->{after_clocks}, on_switches={ctx['before_on']}->{after_on}"


def _verify_timer_16m35s(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    elements = eng.get_screen_data(max_elements=50).get("elements") or []
    blob = " | ".join(f"{e.get('label', '')} {e.get('desc', '')}" for e in elements)
    ok = "16m 35s" in blob or "16 minutes, 35 seconds" in blob
    return ok, f"timer_display_matched={ok}"


def _verify_tasks_db(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/org.tasks/databases/database \"SELECT title FROM tasks WHERE deleted = 0;\" 2>/dev/null").strip()
    ok = "Submit benchmark report" in out
    return ok, f"sqlite_titles={out!r}"


def _verify_math_100(_adb: AdbDevice, eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    elements = eng.get_screen_data(max_elements=40).get("elements") or []
    res_el = next((e for e in elements if e.get("resource_id") == "result"), None)
    val = str(res_el.get("label")) if res_el else ""
    return val == "100", f"result_display={val!r}"


def _setup_audio_recorder(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    pkg = "com.dimowner.audiorecorder"
    adb.clear_app_data(pkg)
    adb.grant_all_permissions(pkg)
    adb.shell("rm -rf /sdcard/Android/data/com.dimowner.audiorecorder/files/* /sdcard/Records/* /sdcard/Music/records/* 2>/dev/null || true")
    adb.launch_app(pkg, wait=True)
    time.sleep(0.8)
    return {}


def _verify_audio_file(prefix: str) -> Callable[..., tuple[bool, str]]:
    def _verify(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
        out = adb.shell(f"find /sdcard/ -name '{prefix}*.m4a' -exec ls -l {{}} + 2>/dev/null").strip()
        if not out:
            return False, f"no '{prefix}*.m4a' found on /sdcard"
        parts = out.splitlines()[0].split()
        size = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        return size > 1000, f"artifact={parts[-1]}, size_bytes={size}"

    return _verify


def _verify_contacts_ada(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("content query --uri content://com.android.contacts/data --projection display_name:data1 2>/dev/null").strip()
    has_name = "Ada" in out
    has_phone = "555-0199" in out or "5550199" in out
    ok = has_name and has_phone
    return ok, f"name={has_name}, phone={has_phone}"


def _verify_calendar_event(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/com.simplemobiletools.calendar.pro/databases/events.db \"SELECT title, location FROM events;\" 2>/dev/null").strip()
    ok = "Architecture Sync" in out and "Room 402" in out
    return ok, f"sqlite_events={out!r}"


def _verify_broccoli_recipe(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    out = adb.shell("sqlite3 /data/data/com.flauschcode.broccoli/databases/broccoli \"SELECT title, preparationTime, ingredients FROM recipes;\" 2>/dev/null").strip()
    ok = "Pasta Pesto" in out and "15 mins" in out and "Pasta, Basil, Garlic" in out
    return ok, f"sqlite_recipes={out!r}"


def _setup_markor(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient) -> dict[str, Any]:
    pkg = "net.gsantner.markor"
    adb.shell("rm -rf /sdcard/Documents/markor/bench_log* /sdcard/Documents/markor/2026-* /sdcard/Documents/bench_log* 2>/dev/null || true")
    adb.clear_app_data(pkg)
    adb.grant_all_permissions(pkg)
    adb.launch_app(pkg, wait=True)
    time.sleep(0.8)
    return {}


def _verify_markor_note(adb: AdbDevice, _eng: AndroidEngine, _helper: AccessibilityHelperClient, _ctx: dict[str, Any]) -> tuple[bool, str]:
    path_out = adb.shell("find /sdcard/Documents -name 'bench_log*.md' 2>/dev/null | head -n 1").strip()
    if not path_out:
        return False, "bench_log.md missing under /sdcard/Documents"
    local_tmp = Path("/tmp/agentdroid_verify_bench_log.md")
    local_tmp.unlink(missing_ok=True)
    adb.pull_file(path_out, str(local_tmp))
    text = local_tmp.read_text(encoding="utf-8", errors="replace") if local_tmp.exists() else ""
    ok = "Verified on Redroid" in text
    return ok, f"remote={path_out}, bytes={len(text.encode('utf-8'))}, content_match={ok}"


TASKS: list[TaskSpec] = [
    # --- Tier 1: Simple (Single-screen state / direct scroll) ---
    TaskSpec(
        task_id="ClockStopWatchRunning",
        app_name="Clock",
        package="com.android.deskclock",
        tier="Simple",
        goal="Switch to the STOPWATCH tab and tap START to start the stopwatch.",
        max_steps=8,
        compound_steps=["wait-text:STOPWATCH@5", "click:STOPWATCH", "wait-text:START@5", "click:START", "wait-text:Pause@5"],
        setup_fn=_setup_clean_launch("com.android.deskclock"),
        verify_fn=_verify_stopwatch_running,
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=38.0,
        baseline_actions=2,
        min_steps_before_done=2,
    ),
    TaskSpec(
        task_id="ClockStopWatchPausedVerify",
        app_name="Clock",
        package="com.android.deskclock",
        tier="Simple",
        goal="Tap Pause to pause the running stopwatch.",
        max_steps=8,
        compound_steps=["click:Pause", "wait-text:Start@5"],
        setup_fn=_setup_stopwatch_running,
        verify_fn=_verify_stopwatch_paused,
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=97.0,
        baseline_actions=4,
        min_steps_before_done=1,
    ),
    TaskSpec(
        task_id="SettingsNavigateAboutPhone",
        app_name="Settings",
        package="com.android.settings",
        tier="Simple",
        goal="Scroll down Settings and open 'About phone' so Android version and Device name are visible.",
        max_steps=8,
        compound_steps=["scroll-to:About phone", "click:About phone", "wait-text:Android version@5"],
        setup_fn=_setup_clean_launch("com.android.settings"),
        verify_fn=_verify_about_phone,
        min_steps_before_done=2,
    ),
    # --- Tier 2: Medium (Multi-tap entry, alarms, tasks, default audio) ---
    TaskSpec(
        task_id="DeskClockAddAlarm",
        app_name="Clock",
        package="com.android.deskclock",
        tier="Medium",
        goal="Tap Add alarm (+) and confirm OK to create and enable a new alarm.",
        max_steps=10,
        compound_steps=["wait-text:Add alarm@5", "click:Add alarm", "wait-text:OK@5", "click:OK", "sleep:0.4"],
        setup_fn=_setup_deskclock_alarm,
        verify_fn=_verify_deskclock_alarm,
        cleanup_fn=lambda adb: adb.clear_app_data("com.android.deskclock"),
        min_steps_before_done=2,
    ),
    TaskSpec(
        task_id="ClockTimerEntry",
        app_name="Clock",
        package="com.android.deskclock",
        tier="Medium",
        goal="Switch to the TIMER tab and enter digits 1, 6, 3, 5 in order so the display shows 16m 35s. Do not start the timer.",
        max_steps=12,
        compound_steps=["wait-text:TIMER@5", "click:TIMER", "sleep:0.3", "wait-text:timer_setup_digit_1@5", "click:1", "click:6", "click:3", "click:5", "wait-text:16m 35s@5"],
        setup_fn=_setup_clean_launch("com.android.deskclock"),
        verify_fn=_verify_timer_16m35s,
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=57.0,
        baseline_actions=6,
        min_steps_before_done=5,
    ),
    TaskSpec(
        task_id="TasksAddTask",
        app_name="Tasks",
        package="org.tasks",
        tier="Medium",
        goal="Tap Create new task, fill the title with 'Submit benchmark report', and tap Save.",
        max_steps=10,
        compound_steps=["wait-text:Create new task@5", "click:Create new task", "wait-text:title@5", "fill:title=Submit benchmark report", "hide-keyboard", "click:Save", "wait-text:Submit benchmark report@5"],
        setup_fn=_setup_clean_launch("org.tasks", grant=True),
        verify_fn=_verify_tasks_db,
        baseline_source="AndroidWorld App",
        min_steps_before_done=3,
    ),
    TaskSpec(
        task_id="FossifyMathCompute",
        app_name="Fossify Math",
        package="org.fossify.math",
        tier="Medium",
        goal="Press calculator buttons '4', '2', '+', '5', '8', '=' in exact order to compute 42 + 58 = 100.",
        max_steps=14,
        compound_steps=["wait-text:btn_4@5", "click:btn_4", "click:btn_2", "click:btn_plus", "click:btn_5", "click:btn_8", "click:btn_equals", "wait-text:100@5"],
        setup_fn=_setup_clean_launch("org.fossify.math"),
        verify_fn=_verify_math_100,
        baseline_source="Mobilebox parity APK",
        min_steps_before_done=6,
    ),
    TaskSpec(
        task_id="AudioRecorderRecordAudio",
        app_name="Audio Recorder",
        package="com.dimowner.audiorecorder",
        tier="Medium",
        goal="Complete onboarding if shown (Get started, Apply), tap record to start recording, wait 1.5s once, stop recording, and tap Save.",
        max_steps=14,
        compound_steps=[
            "wait-any:Get started|Apply|Recording: %s@5",
            "if-visible:Get started->click:Get started",
            "wait-any:Apply|Recording: %s@5",
            "if-visible:Apply->click:Apply",
            "wait-text:Recording: %s@5",
            "click:Recording: %s",
            "sleep:1.5",
            "click:btn_record_stop",
            "wait-text:Save@5",
            "click:Save",
            "sleep:0.6",
        ],
        setup_fn=_setup_audio_recorder,
        verify_fn=_verify_audio_file("Record-1"),
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=62.0,
        baseline_actions=6,
        min_steps_before_done=5,
    ),
    # --- Tier 3: Complex (Multi-field forms, full onboarding, custom filenames, disk/DB verify) ---
    TaskSpec(
        task_id="ContactsAddContact",
        app_name="Contacts",
        package="com.android.contacts",
        tier="Complex",
        goal="Create a new contact with name 'Ada' and phone number '5550199', and save it.",
        max_steps=14,
        compound_steps=[
            "wait-text:Create new contact@5",
            "click:Create new contact",
            "sleep:0.4",
            "if-visible:CANCEL->click:CANCEL",
            "wait-text:SAVE@5",
            "fill:EditText=Ada",
            "hide-keyboard",
            "tap:556,1297",
            "type:5550199",
            "hide-keyboard",
            "click:SAVE",
            "sleep:0.4",
        ],
        setup_fn=_setup_clean_launch("com.android.contacts", grant=True),
        verify_fn=_verify_contacts_ada,
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=81.0,
        baseline_actions=7,
        min_steps_before_done=4,
    ),
    TaskSpec(
        task_id="SimpleCalendarAddOneEvent",
        app_name="Simple Calendar",
        package="com.simplemobiletools.calendar.pro",
        tier="Complex",
        goal="Tap New Event to create a calendar event, enter title 'Architecture Sync' and location 'Room 402', and tap Save.",
        max_steps=14,
        compound_steps=[
            "wait-text:New Event@5",
            "click:New Event",
            "sleep:0.3",
            "if-visible:Event->click:Event",
            "wait-text:event_title@5",
            "fill:event_title=Architecture Sync",
            "hide-keyboard",
            "fill:event_location=Room 402",
            "hide-keyboard",
            "click:Save",
            "sleep:0.3",
            "if-visible:OK->click:OK",
            "sleep:0.3",
        ],
        setup_fn=_setup_clean_launch("com.simplemobiletools.calendar.pro", grant=True),
        verify_fn=_verify_calendar_event,
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=184.0,
        baseline_actions=18,
        min_steps_before_done=4,
    ),
    TaskSpec(
        task_id="BroccoliAddSingleRecipe",
        app_name="Broccoli",
        package="com.flauschcode.broccoli",
        tier="Complex",
        goal="Add a new recipe titled 'Pasta Pesto' with preparation time '15 mins' and ingredients 'Pasta, Basil, Garlic', then tap SAVE.",
        max_steps=14,
        compound_steps=[
            "wait-text:New Recipe@5",
            "click:New Recipe",
            "wait-text:new_title@5",
            "fill:new_title=Pasta Pesto",
            "hide-keyboard",
            "fill:new_preparation_time=15 mins",
            "hide-keyboard",
            "fill:new_ingredients=Pasta, Basil, Garlic",
            "hide-keyboard",
            "click:SAVE",
            "sleep:0.4",
        ],
        setup_fn=_setup_clean_launch("com.flauschcode.broccoli", grant=True),
        verify_fn=_verify_broccoli_recipe,
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=138.0,
        baseline_actions=13,
        min_steps_before_done=5,
    ),
    TaskSpec(
        task_id="AudioRecorderRecordAudioWithFileName",
        app_name="Audio Recorder",
        package="com.dimowner.audiorecorder",
        tier="Complex",
        goal="Complete onboarding if shown (Get started, Apply), tap record to start recording, wait 1.5s once, stop recording, type 'interview_clip' as filename, and tap Save.",
        max_steps=16,
        compound_steps=[
            "wait-any:Get started|Apply|Recording: %s@5",
            "if-visible:Get started->click:Get started",
            "wait-any:Apply|Recording: %s@5",
            "if-visible:Apply->click:Apply",
            "wait-text:Recording: %s@5",
            "click:Recording: %s",
            "sleep:1.5",
            "click:btn_record_stop",
            "wait-text:input_name@5",
            "fill:input_name=interview_clip",
            "hide-keyboard",
            "click:Save",
            "sleep:0.6",
        ],
        setup_fn=_setup_audio_recorder,
        verify_fn=_verify_audio_file("interview_clip"),
        baseline_source="Vostride / AndroidWorld",
        baseline_sec=106.0,
        baseline_actions=10,
        min_steps_before_done=6,
    ),
    TaskSpec(
        task_id="MarkorCreateAndSaveNote",
        app_name="Markor",
        package="net.gsantner.markor",
        tier="Complex",
        goal="Pass onboarding (NEXT/DONE/OK), tap create new file, fill file Name with 'bench_log' then tap OK, write 'Verified on Redroid' in the note editor, and tap Save.",
        max_steps=18,
        compound_steps=[
            "wait-text:NEXT@5",
            "click:NEXT",
            "sleep:0.25",
            "click:NEXT",
            "sleep:0.25",
            "click:NEXT",
            "sleep:0.25",
            "click:NEXT",
            "sleep:0.25",
            "click:DONE",
            "wait-text:OK@5",
            "click:OK",
            "wait-text:Create a new file or folder@5",
            "click:Create a new file or folder",
            "wait-text:new_file_dialog__name@5",
            "fill:new_file_dialog__name=bench_log",
            "hide-keyboard",
            "click:OK",
            "wait-text:document__fragment__edit__highlighting_editor@5",
            "fill:document__fragment__edit__highlighting_editor=Verified on Redroid",
            "sleep:0.3",
            "hide-keyboard",
            "sleep:0.3",
            "click:action_save",
            "sleep:0.5",
            "key:BACK",
            "sleep:0.5",
        ],
        setup_fn=_setup_markor,
        verify_fn=_verify_markor_note,
        baseline_source="Vostride / AndroidWorld (+onboarding)",
        baseline_sec=64.0,
        baseline_actions=6,
        min_steps_before_done=9,
    ),
]


# ---------------------------------------------------------------------------
# Track Runners
# ---------------------------------------------------------------------------


def run_compound_task(task: TaskSpec, adb: AdbDevice, eng: AndroidEngine, helper: AccessibilityHelperClient) -> dict[str, Any]:
    """Execute one task via single-turn AgentDroid compound burst and verify ground truth."""
    adb.clear_logs()
    ctx = task.setup_fn(adb, eng, helper)
    t0 = time.perf_counter()
    results = eng.execute_action_burst(task.compound_steps)
    wall_sec = round(time.perf_counter() - t0, 3)

    passed, evidence = task.verify_fn(adb, eng, helper, ctx)
    crashes = adb.collect_crashes(task.package)
    ok = bool(passed and not crashes.has_crashes)

    if task.cleanup_fn:
        task.cleanup_fn(adb)
    else:
        adb.stop_app(task.package)

    return {
        "task_id": task.task_id,
        "app": task.app_name,
        "tier": task.tier,
        "mode": "compound",
        "ok": ok,
        "wall_clock_sec": wall_sec,
        "steps_executed": len(task.compound_steps),
        "llm_turns": 1,
        "crashes": crashes.has_crashes,
        "verification": evidence,
        "step_failures": [r for r in results if isinstance(r, dict) and r.get("success") is False],
    }


def run_jev_task(
    task: TaskSpec,
    adb: AdbDevice,
    eng: AndroidEngine,
    helper: AccessibilityHelperClient,
    client: TypeSafeAIClient,
) -> dict[str, Any]:
    """Execute one task via autonomous closed-loop AgentDroid + Jev and verify ground truth."""
    adb.clear_logs()
    ctx = task.setup_fn(adb, eng, helper)

    step_history: list[str] = []
    trace: list[dict[str, Any]] = []
    latencies: list[float] = []
    payload_chars = 0
    terminated_reason = "max_steps"

    t0 = time.perf_counter()
    for step in range(1, task.max_steps + 1):
        ui = eng.get_screen_data(max_elements=80)
        payload_chars += len(ui.get("formatted_text", ""))

        try:
            d = client.rank_next_action(ui, task.goal, step_history=step_history)
        except Exception as exc:
            terminated_reason = f"api_error: {type(exc).__name__}"
            break
        act_key = d.get("action_key", "wait")
        act_type = d.get("action_type", act_key)
        act_label = d.get("action_label", act_key)
        lat = float(d.get("latency_ms", 0.0))
        latencies.append(lat)

        trace.append(
            {
                "step": step,
                "action": act_key,
                "label": act_label,
                "confidence": round(float(d.get("confidence", 0.0)), 3),
                "goal_met_prob": round(float(d.get("goal_met_probability", 0.0)), 3),
                "latency_ms": lat,
            }
        )

        if act_key == "done":
            terminated_reason = "agent_done"
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
            terminated_reason = "goal_met_noul"
            break

    wall_sec = round(time.perf_counter() - t0, 3)

    passed, evidence = task.verify_fn(adb, eng, helper, ctx)
    crashes = adb.collect_crashes(task.package)
    ok = bool(passed and not crashes.has_crashes)

    if task.cleanup_fn:
        task.cleanup_fn(adb)
    else:
        adb.stop_app(task.package)

    return {
        "task_id": task.task_id,
        "app": task.app_name,
        "tier": task.tier,
        "mode": "jev",
        "ok": ok,
        "wall_clock_sec": wall_sec,
        "steps_executed": len(trace),
        "max_steps": task.max_steps,
        "terminated_reason": terminated_reason,
        "mean_ai_latency_ms": round(statistics.mean(latencies), 1) if latencies else 0.0,
        "total_prompt_est_tokens": math.ceil(payload_chars / 4),
        "crashes": crashes.has_crashes,
        "verification": evidence,
        "baseline_source": task.baseline_source,
        "baseline_sec": task.baseline_sec,
        "baseline_actions": task.baseline_actions,
        "trace": trace,
    }


def summarize_track(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute overall and complexity-tier aggregates for a benchmark track."""
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

    return {
        "overall": _agg(rows),
        "by_tier": {tier: _agg(by_tier[tier]) for tier in ("Simple", "Medium", "Complex") if by_tier[tier]},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run verified AgentDroid E2E benchmarks.")
    parser.add_argument("-s", "--serial", default="127.0.0.1:5555")
    parser.add_argument("--mode", choices=("both", "jev", "compound"), default="both")
    parser.add_argument("--api-key", default=os.environ.get("TYPESAFE_API_KEY", ""))
    parser.add_argument("--output", default=str(RESULTS_PATH))
    parser.add_argument("--merge", action="store_true", help="Preserve existing tracks in output JSON when running a single mode.")
    args = parser.parse_args()

    out_path = Path(args.output)
    existing_modes: dict[str, Any] = {}
    if args.merge and out_path.exists():
        try:
            existing_modes = json.loads(out_path.read_text(encoding="utf-8")).get("modes", {})
        except Exception:
            existing_modes = {}

    adb = AdbDevice(serial=args.serial)
    if not adb.connect(timeout=10.0):
        raise RuntimeError(f"Cannot connect to ADB device {args.serial}")
    adb.ensure_root()
    helper = AccessibilityHelperClient(adb)
    if not helper.ensure_ready():
        raise RuntimeError("Artemis Accessibility Helper is not ready")
    helper._ensure_input_daemon(force=False)
    eng = AndroidEngine(adb=adb)

    client: TypeSafeAIClient | None = None
    if args.mode in ("both", "jev"):
        if not args.api_key:
            raise ValueError("TYPESAFE_API_KEY env var or --api-key is required for mode=jev/both")
        client = TypeSafeAIClient(api_key=args.api_key)

    report: dict[str, Any] = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "device_serial": args.serial,
        "device_model": adb.shell("getprop ro.product.model").strip(),
        "android_release": adb.shell("getprop ro.build.version.release").strip(),
        "task_count": len(TASKS),
        "modes": dict(existing_modes),
    }

    if args.mode in ("both", "compound"):
        logger.info("=== Running Track 1: AgentDroid Compound / MCP Single-Turn Burst ===")
        comp_rows = []
        for idx, task in enumerate(TASKS, 1):
            row = run_compound_task(task, adb, eng, helper)
            comp_rows.append(row)
            status = "PASS" if row["ok"] else "FAIL"
            logger.info(
                f"  [{idx}/{len(TASKS)}] {task.tier:7s} | {task.task_id:38s} | {status} | "
                f"{row['wall_clock_sec']:5.2f}s | {row['steps_executed']:2d} steps | {row['verification']}"
            )
            if idx % 4 == 0:
                adb.trim_background_apps()
        report["modes"]["compound"] = {"summary": summarize_track(comp_rows), "tasks": comp_rows}

    if args.mode in ("both", "jev") and client is not None:
        logger.info("=== Running Track 2: AgentDroid + TypeSafe AI (Jev System One Autonomous Loop) ===")
        client.is_valid()  # Warm persistent TLS connection outside per-task timing
        jev_rows = []
        for idx, task in enumerate(TASKS, 1):
            row = run_jev_task(task, adb, eng, helper, client)
            jev_rows.append(row)
            status = "PASS" if row["ok"] else "FAIL"
            logger.info(
                f"  [{idx}/{len(TASKS)}] {task.tier:7s} | {task.task_id:38s} | {status} | "
                f"{row['wall_clock_sec']:5.2f}s | {row['steps_executed']:2d} steps | "
                f"ai={row['mean_ai_latency_ms']:5.1f}ms | {row['terminated_reason']} | {row['verification']}"
            )
            if idx % 4 == 0:
                adb.trim_background_apps()
        client.close()
        report["modes"]["jev"] = {"summary": summarize_track(jev_rows), "tasks": jev_rows}

    adb.trim_background_apps()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    logger.info(f"Saved verifiable E2E report to {out_path}")


if __name__ == "__main__":
    main()
