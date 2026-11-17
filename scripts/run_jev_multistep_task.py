#!/usr/bin/env python3
"""Execute a complex multi-step task driven by TypeSafe AI (Jev System One) in live watch mode."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine
from agentdroid.helper import AccessibilityHelperClient
from agentdroid.typesafe_ai import TypeSafeAIClient
from agentdroid.watcher import LiveWatcher

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("jev_runner")

API_KEY = os.environ.get(
    "TYPESAFE_API_KEY",
    "",
)


def run_complex_task(serial: str = "127.0.0.1:5555", watch: bool = True) -> None:
    adb = AdbDevice(serial)
    engine = AndroidEngine(adb)
    helper = AccessibilityHelperClient(adb)
    jev = TypeSafeAIClient(api_key=API_KEY)

    watcher = None
    if watch:
        logger.info("Starting live visual simulator overlay (scrcpy watch mode)...")
        watcher = LiveWatcher(
            serial=serial,
            watch=True,
            interactive_control=False,
            always_on_top=True,
            window_width=412,
            window_height=892,
        )
        watcher_info = watcher.start()
        logger.info(f"Watch overlay active: {watcher_info}")
        time.sleep(1.2)

    try:
        pkg = "com.dimowner.audiorecorder"
        logger.info("Initializing app environment: clearing and granting permissions...")
        adb.clear_app_data(pkg)
        adb.grant_all_permissions(pkg)
        adb.launch_app(pkg)
        time.sleep(0.8)

        target_name = "JevSprint"
        goal = f"Record an audio clip and save it with filename '{target_name}' using Audio Recorder app."
        logger.info(f"Target Goal: {goal}")

        steps_log = []
        total_start = time.perf_counter()

        step_num = 1
        max_steps = 10
        is_recording = False

        while step_num <= max_steps:
            ui = helper.dump_compact_ui()
            fg = ui.get("foreground", {})
            elements = ui.get("elements", [])

            # Filter non-systemui clickable and interactive elements
            actionable = [el for el in elements if not el.get("systemui")]

            candidates: dict[str, str] = {}
            for el in actionable:
                eid = el.get("id")
                lbl = el.get("label") or el.get("resource_id") or ""
                rid = el.get("resource_id") or ""
                cls_name = el.get("class", "View")

                # Provide semantic descriptions for Jev
                desc_parts = []
                if lbl:
                    desc_parts.append(f"'{lbl}'")
                if rid and rid != lbl:
                    desc_parts.append(f"[{rid}]")
                desc_parts.append(f"({cls_name})")

                # Contextual intent hints
                if "btn_action" in rid or "Get started" in lbl:
                    desc_parts.append("-> Start setup/app onboarding")
                elif "btn_apply" in rid or "Apply" in lbl:
                    desc_parts.append("-> Apply settings and proceed to main recording screen")
                elif "btn_record_stop" in rid:
                    desc_parts.append("-> STOP the active recording and open save dialog")
                elif "btn_record" in rid or "Recording" in lbl:
                    desc_parts.append("-> START a new audio recording")
                elif "dialog_positive_btn" in rid or "Save" in lbl:
                    desc_parts.append(f"-> SAVE the audio recording as '{target_name}'")

                candidates[f"tap_{eid}"] = "Tap " + " ".join(desc_parts)

            has_edit_text = any(el.get("class") == "EditText" or el.get("editable") for el in actionable)
            if has_edit_text:
                candidates["type_filename"] = f"Enter custom filename '{target_name}' into the name text field"

            state_desc = (
                f"Goal: {goal}\n"
                f"Active Screen Activity: {fg.get('activity')}\n"
                f"Is audio currently recording: {is_recording}\n"
                f"Step history: {[s['action'] for s in steps_log]}"
            )

            questions = {
                "next_action": {
                    "type": "choice",
                    "instructions": f"Select the single best next action to achieve the goal: '{goal}'.",
                    "criteria": candidates,
                },
                "is_goal_met": {
                    "type": "noul",
                    "instructions": f"Has the audio clip '{target_name}' been saved to storage and visible in the app?",
                },
            }

            jev_res = jev.decide(state_desc, questions)
            ans = jev_res.get("answers", {})
            choice_data = ans.get("next_action", {})
            action_choice = choice_data.get("choice", "wait")
            confidence = choice_data.get("confidence", 0.0)
            goal_noul = ans.get("is_goal_met", {}).get("noul", 0.0)
            latency_ms = jev_res.get("latency_ms", 0.0)

            logger.info(f"--- STEP {step_num} ---")
            logger.info(f"Jev Decision: {action_choice} (confidence={confidence:.2f}, goal_met={goal_noul:.2f}) | Latency: {latency_ms}ms")

            if goal_noul >= 0.80:
                logger.info(f"Goal verified complete by Jev at step {step_num}!")
                break

            # Execute action
            t_exec_start = time.perf_counter()
            exec_desc = ""

            if action_choice == "type_filename":
                engine.execute_action({"type": "fill", "selector": "input_name", "text": target_name})
                exec_desc = f"Filled '{target_name}' into input_name"
            elif action_choice.startswith("tap_"):
                target_id = int(action_choice.split("_")[1])
                matched = next((e for e in elements if e.get("id") == target_id), None)
                if matched:
                    selector = matched.get("resource_id") or matched.get("label")
                    engine.execute_action({"type": "click", "selector": selector})
                    exec_desc = f"Tapped '{selector}' (#{target_id})"

                    if "btn_record" in str(selector) or "Recording" in str(selector):
                        is_recording = True
                        logger.info("Recording started. Capturing 2.0s audio clip...")
                        time.sleep(2.0)
                        exec_desc += " + recorded 2.0s audio"
                    elif "btn_record_stop" in str(selector):
                        is_recording = False
                else:
                    exec_desc = f"Matched element {target_id} not found"
            else:
                time.sleep(0.5)
                exec_desc = "Waited 0.5s"

            exec_ms = round((time.perf_counter() - t_exec_start) * 1000, 1)
            logger.info(f"Execution: {exec_desc} | Input Latency: {exec_ms}ms")

            steps_log.append({
                "step": step_num,
                "action": action_choice,
                "description": exec_desc,
                "jev_latency_ms": latency_ms,
                "exec_latency_ms": exec_ms,
                "confidence": confidence,
            })

            step_num += 1
            time.sleep(0.4)

        total_sec = round(time.perf_counter() - total_start, 2)

        # Artifact verification
        find_out = adb.shell(f"find /sdcard/ -name '{target_name}*' 2>/dev/null").strip()
        verified_on_disk = f"{target_name}.m4a" in find_out

        print("\n" + "=" * 65)
        print("🏆 JEV AUTONOMOUS TASK RUN SUMMARY (WATCH MODE)")
        print("=" * 65)
        print(f"Goal:              {goal}")
        print(f"Total Time:        {total_sec}s")
        print(f"Steps Taken:       {len(steps_log)}")
        avg_jev = sum(s["jev_latency_ms"] for s in steps_log) / max(1, len(steps_log))
        print(f"Avg Jev Latency:   {avg_jev:.1f}ms per decision")
        print(f"Storage Artifact:  {find_out}")
        print(f"Verification:      {'PASS' if verified_on_disk else 'FAIL'}")
        print("-" * 65)
        print("Step Breakdown:")
        for s in steps_log:
            print(f"  Step {s['step']}: {s['description']} (Jev: {s['jev_latency_ms']}ms, Exec: {s['exec_latency_ms']}ms)")
        print("=" * 65)

    finally:
        if watcher:
            logger.info("Closing scrcpy watch overlay...")
            watcher.stop(force=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--serial", default="127.0.0.1:5555")
    parser.add_argument("--no-watch", action="store_true")
    args = parser.parse_args()
    run_complex_task(serial=args.serial, watch=not args.no_watch)
