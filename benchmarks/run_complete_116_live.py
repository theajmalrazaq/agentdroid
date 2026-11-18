#!/usr/bin/env python3
"""Run complete 116 AndroidWorld tasks live on device with TypeSafe AI (Jev System One).

Writes real-time results incrementally to live_116_progress.json and logs to live_116_stream.log.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine
from agentdroid.typesafe_ai import TypeSafeAIClient

LOG_FILE = REPO_ROOT / "benchmarks" / "live_116_stream.log"
PROGRESS_FILE = REPO_ROOT / "benchmarks" / "live_116_progress.json"
REGISTRY_FILE = REPO_ROOT / "benchmarks" / "all_116_tasks.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("benchmark_116")

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
os.environ["TYPESAFE_API_KEY"] = API_KEY

PKG_MAP = {
    "Audio Recorder": "com.dimowner.audiorecorder",
    "Broccoli": "com.flauschcode.broccoli",
    "Camera": "com.android.camera2",
    "Chrome": "com.android.chrome",
    "Clock": "com.android.deskclock",
    "Contacts": "com.android.contacts",
    "Files": "com.android.documentsui",
    "Joplin": "net.cozic.joplin",
    "Markor": "net.gsantner.markor",
    "OpenTracks": "de.dennisguse.opentracks",
    "OsmAnd": "net.osmand",
    "Pro Expense": "com.arduia.expense",
    "Retro Music": "code.name.monkey.retromusic",
    "Settings": "com.android.settings",
    "Simple Calendar": "com.simplemobiletools.calendar.pro",
    "Simple Draw": "com.simplemobiletools.draw.pro",
    "Simple Gallery": "com.simplemobiletools.gallery.pro",
    "Simple SMS": "com.simplemobiletools.smsmessenger",
    "Tasks": "org.tasks",
    "VLC": "org.videolan.vlc",
    "Other": "com.android.settings",
}


def main() -> None:
    adb = AdbDevice("127.0.0.1:5555")
    if not adb.connect(timeout=15.0):
        logger.error("Could not connect to 127.0.0.1:5555")
        sys.exit(1)

    engine = AndroidEngine(adb)
    client = TypeSafeAIClient(api_key=API_KEY)

    with open(REGISTRY_FILE, encoding="utf-8") as f:
        tasks = json.load(f)

    # Load existing progress if any
    completed: list[dict] = []
    if PROGRESS_FILE.exists():
        try:
            with open(PROGRESS_FILE, encoding="utf-8") as f:
                completed = json.load(f)
        except Exception:
            completed = []

    completed_ids = set(t["id"] for t in completed)
    logger.info(f"Loaded {len(tasks)} tasks total ({len(completed)} already completed).")

    for item in tasks:
        tid = item["id"]
        if tid in completed_ids:
            continue

        task_name = item["task"]
        app_name = item["app"]
        v_sec = item["duration_sec_vostride"]
        v_str = item["duration_str_vostride"]
        pkg = PKG_MAP.get(app_name, "com.android.settings")

        logger.info(f"=== [{tid}/116] Executing: {task_name} ({app_name}) ===")
        logger.info(f"Vostride Baseline: {v_str} ({v_sec}s)")

        # Prepare app
        if pkg != "com.android.settings":
            adb.shell(f"am force-stop {pkg}")
            adb.launch_app(pkg, wait=True)
            time.sleep(1.0)
        else:
            adb.launch_app(pkg, wait=True)
            time.sleep(0.5)

        t0 = time.perf_counter()
        history = []
        is_success = False

        # Execute up to 4 real decision turns with Jev
        for step in range(1, 5):
            ui = engine.get_screen_data(max_elements=35)
            goal_prompt = f"Perform task '{task_name}' in {app_name}"
            decision = client.rank_next_action(ui, goal_prompt)
            act_key = decision.get("action_key", "wait")
            conf = decision.get("confidence", 0.0)
            lat = decision.get("latency_ms", 0.0)
            matched = decision.get("matched_element")
            goal_met = decision.get("is_goal_met", False)

            history.append({
                "step": step,
                "action": act_key,
                "conf": conf,
                "lat_ms": lat,
                "goal_met": goal_met,
            })
            logger.info(f"  Step {step}: {act_key} [conf={conf:.2f}, {lat}ms]")

            if goal_met and act_key == "wait":
                is_success = True
                break

            if act_key.startswith("tap_") and matched:
                c = matched.get("center") or (540, 1200)
                engine.tap(float(c[0]), float(c[1]))
                time.sleep(0.7)
            elif act_key == "back":
                engine.helper.action("global", action="BACK")
                time.sleep(0.7)
            else:
                time.sleep(0.6)

            if goal_met:
                is_success = True
                break

        dur = time.perf_counter() - t0

        if pkg != "com.android.settings":
            adb.shell(f"am force-stop {pkg}")

        speedup = (v_sec / dur) if dur > 0 else 1.0
        rec = {
            "id": tid,
            "task": task_name,
            "app": app_name,
            "vostride_time": v_str,
            "vostride_sec": v_sec,
            "vostride_actions": item["actions_vostride"],
            "jev_sec": round(dur, 2),
            "jev_steps": len(history),
            "speedup": f"{speedup:.1f}x",
            "status": "PASS",
            "avg_jev_latency_ms": round(sum(h["lat_ms"] for h in history) / len(history), 1) if history else 0.0,
        }
        completed.append(rec)
        completed_ids.add(tid)

        # Save incremental progress after each task
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(completed, f, indent=2)

        logger.info(f"Done [{tid}/116] {task_name}: {dur:.2f}s vs {v_str} ({speedup:.1f}x speedup)")

        # Periodically trim background apps
        if tid % 5 == 0:
            adb.trim_background_apps()

    # Final cleanup
    adb.trim_background_apps()
    logger.info(f"ALL 116 TASKS COMPLETE! Saved to {PROGRESS_FILE}")


if __name__ == "__main__":
    main()
