#!/usr/bin/env python3
"""Extract and cache all AndroidWorld benchmark tasks and prompts."""

import json
from pathlib import Path
import re
import urllib.request

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_FILE = REPO_ROOT / "benchmarks" / "android_world_tasks.json"


def fetch_all_tasks() -> list[dict[str, object]]:
    url = "https://vostride.com/benchmark/android-world"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8")

    matches = re.findall(
        r"\\\"task\\\":\\\"([^\\\"]+)\\\",\\\"app\\\":\\\"([^\\\"]+)\\\",\\\"runId\\\":\\\"([^\\\"]+)\\\",\\\"passed\\\":(true|false),.*?\\\"goal\\\":\\\"([^\\\"]+)\\\",\\\"complexity\\\":([0-9.]+),\\\"durationS\\\":([0-9.]+),\\\"actions\\\":([0-9]+)",
        html,
    )
    tasks = []
    seen = set()
    for t_name, app, run_id, passed_str, goal_raw, comp_str, dur_str, act_str in matches:
        if t_name in seen:
            continue
        seen.add(t_name)
        goal = goal_raw.encode("utf-8").decode("unicode_escape", errors="replace")
        tasks.append(
            {
                "task": t_name,
                "app": app,
                "goal": goal,
                "complexity": float(comp_str),
                "duration_sec_vostride": float(dur_str),
                "actions_vostride": int(act_str),
                "passed_vostride": passed_str == "true",
            }
        )
    tasks.sort(key=lambda x: (str(x["app"]), str(x["task"])))
    TASKS_FILE.parent.mkdir(parents=True, exist_ok=True)
    TASKS_FILE.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Extracted {len(tasks)} AndroidWorld tasks across {len(set(t['app'] for t in tasks))} apps to {TASKS_FILE}")
    return tasks


if __name__ == "__main__":
    fetch_all_tasks()
