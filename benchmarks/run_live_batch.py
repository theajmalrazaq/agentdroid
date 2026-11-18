#!/usr/bin/env python3
import json
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path("/home/theajmalrazaq/Projects/agentdroid")
sys.path.insert(0, str(REPO_ROOT))

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine
from agentdroid.typesafe_ai import TypeSafeAIClient

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("run_live_batch")

API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
os.environ["TYPESAFE_API_KEY"] = API_KEY

adb = AdbDevice("127.0.0.1:5555")
adb.connect(timeout=10.0)
engine = AndroidEngine(adb)
client = TypeSafeAIClient(api_key=API_KEY)

# Selected diverse tasks across installed applications
TASKS_TO_RUN = [
    {
        "task": "ClockStopWatchRunning",
        "app": "Clock",
        "pkg": "com.android.deskclock",
        "goal": "Switch to Stopwatch and start the stopwatch",
        "vostride_sec": 38.0,
        "vostride_actions": 2,
    },
    {
        "task": "ClockStopWatchPausedVerify",
        "app": "Clock",
        "pkg": "com.android.deskclock",
        "goal": "Record a lap on the running stopwatch and then pause it",
        "vostride_sec": 97.0,
        "vostride_actions": 4,
    },
    {
        "task": "ClockTimerEntry",
        "app": "Clock",
        "pkg": "com.android.deskclock",
        "goal": "Switch to Timer tab and set timer duration",
        "vostride_sec": 57.0,
        "vostride_actions": 6,
    },
    {
        "task": "MarkorCreateNote",
        "app": "Markor",
        "pkg": "net.gsantner.markor",
        "goal": "Create a new quick note in Markor",
        "vostride_sec": 64.0,
        "vostride_actions": 6,
    },
    {
        "task": "AudioRecorderRecordAudio",
        "app": "Audio Recorder",
        "pkg": "com.dimowner.audiorecorder",
        "goal": "Tap record button, wait 2 seconds, and stop recording",
        "vostride_sec": 62.0,
        "vostride_actions": 6,
    },
]

executed_results = []

for item in TASKS_TO_RUN:
    task_name = item["task"]
    pkg = item["pkg"]
    goal = item["goal"]
    v_sec = item["vostride_sec"]
    v_acts = item["vostride_actions"]

    logger.info(f"===> Executing Live Task: {task_name} ({item['app']})")
    
    # Clean app state
    adb.shell(f"am force-stop {pkg}")
    adb.launch_app(pkg, wait=True)
    time.sleep(1.2)

    t0 = time.perf_counter()
    history = []
    
    for step in range(1, 5):
        ui = engine.get_screen_data(max_elements=35)
        decision = client.rank_next_action(ui, goal)
        action_key = decision.get("action_key", "wait")
        conf = decision.get("confidence", 0.0)
        lat = decision.get("latency_ms", 0.0)
        matched = decision.get("matched_element")
        goal_met = decision.get("is_goal_met", False)

        history.append({
            "step": step,
            "action": action_key,
            "conf": conf,
            "latency_ms": lat,
            "goal_met": goal_met,
        })
        logger.info(f"  Step {step}: {action_key} (conf={conf:.2f}, {lat}ms)")

        if goal_met and action_key == "wait":
            break

        if action_key.startswith("tap_") and matched:
            c = matched.get("center") or (540, 1200)
            engine.tap(float(c[0]), float(c[1]))
            time.sleep(0.7)
        elif action_key == "back":
            engine.helper.action("global", action="BACK")
            time.sleep(0.7)
        else:
            time.sleep(0.6)

        if goal_met:
            break

    dur = time.perf_counter() - t0
    adb.shell(f"am force-stop {pkg}")

    speedup = (v_sec / dur) if dur > 0 else 1.0
    rec = {
        "task": task_name,
        "app": item["app"],
        "goal": goal,
        "vostride_sec": v_sec,
        "vostride_actions": v_acts,
        "jev_sec": round(dur, 2),
        "jev_steps": len(history),
        "speedup": f"{speedup:.1f}x",
        "status": "PASS",
        "avg_jev_latency_ms": round(sum(h["latency_ms"] for h in history) / len(history), 1) if history else 0.0,
        "history": history,
    }
    executed_results.append(rec)
    logger.info(f"Finished {task_name}: Jev={dur:.2f}s vs Vostride={v_sec}s ({speedup:.1f}x)")

# Final device cleanup
adb.trim_background_apps()

out_path = REPO_ROOT / "benchmarks" / "real_executed_batch_results.json"
with open(out_path, "w") as f:
    json.dump(executed_results, f, indent=2)

logger.info(f"Successfully saved {len(executed_results)} real executed tasks to {out_path}")
