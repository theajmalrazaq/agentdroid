"""Optional cloud autonomous loop subcommand (`agentdroid ai`, powered by TypeSafe AI)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any

from agentdroid.adb import AdbDevice
from agentdroid.watcher import LiveWatcher


def cmd_ai(args: argparse.Namespace) -> int:
    """Run optional cloud-backed autonomous execution via TypeSafe AI (api.typesafe.ai)."""
    from agentdroid.engine import AndroidEngine
    from agentdroid.typesafe_ai import TypeSafeAIClient

    adb = AdbDevice(serial=args.serial)
    if not adb.connect(timeout=15.0):
        print(f"Error: Could not connect to {adb.serial}", file=sys.stderr)
        return 1

    watcher = None
    if getattr(args, "watch", False):
        watcher = LiveWatcher(
            adb.serial,
            watch=True,
            interactive_control=bool(getattr(args, "interactive", False)),
            always_on_top=not getattr(args, "no_always_on_top", False),
            window_width=getattr(args, "window_width", 412),
            window_height=getattr(args, "window_height", 892),
            borderless=bool(getattr(args, "borderless", False)),
        )
        info = watcher.start()
        print(
            f"[agentdroid:ai] Live watcher attached ({info.get('viewer')})",
            file=sys.stderr,
        )

    try:
        if getattr(args, "clear_data", None):
            for pkg in args.clear_data:
                adb.clear_app_data(pkg)
        if getattr(args, "launch", None):
            adb.launch_app(args.launch, wait=True)
            time.sleep(1.0)

        engine = AndroidEngine(adb)
        api_key = (
            getattr(args, "key", None)
            or os.environ.get("TYPESAFE_API_KEY")
            or ""
        )
        client = TypeSafeAIClient(api_key=api_key)
        goal = args.prompt
        max_steps = getattr(args, "max_steps", 10)
        model = getattr(args, "model", "jev-latest")

        print(f"[agentdroid:ai] Goal: '{goal}' | Model: {model} | Device: {adb.serial}")

        history: list[dict[str, Any]] = []
        step_log: list[str] = []
        is_success = False

        for step in range(1, max_steps + 1):
            ui = engine.get_screen_data(max_elements=80)
            decision = client.rank_next_action(ui, goal, model=model, step_history=step_log)
            action_key = decision.get("action_key", "wait")
            action_type = decision.get("action_type") or (
                "fill"
                if action_key.startswith("fill_")
                else "tap"
                if action_key.startswith("tap_")
                else action_key
            )
            fill_text = decision.get("fill_text")
            conf = decision.get("confidence", 0.0)
            latency = decision.get("latency_ms", 0.0)
            matched = decision.get("matched_element")
            is_goal_met = decision.get("is_goal_met", False)

            step_record = {
                "step": step,
                "action": action_key,
                "confidence": conf,
                "latency_ms": latency,
                "goal_met": is_goal_met,
            }
            history.append(step_record)

            label = (
                (matched.get("label") or matched.get("desc") or matched.get("resource_id"))
                if matched
                else ""
            )
            print(
                f"[agentdroid:ai] Step {step}/{max_steps}: {action_key} "
                f"({label or fill_text or 'none'}) [conf={conf:.2f}, {latency}ms]"
            )

            if action_key == "done" or (is_goal_met and action_key == "wait"):
                print(f"✅ [agentdroid:ai] Goal satisfied! '{goal}'")
                is_success = True
                break

            if action_type == "fill" and matched and fill_text is not None:
                center = matched.get("center") or (540, 1200)
                engine.tap(float(center[0]), float(center[1]))
                time.sleep(0.25)
                engine.execute_action({"type": "type", "text": str(fill_text)})
                engine.execute_action({"type": "hide_keyboard"})
                step_log.append(f"Step {step}: Typed '{fill_text}' into '{label or 'field'}'")
                time.sleep(0.4)
            elif action_key.startswith("tap_") and matched:
                center = matched.get("center") or (540, 1200)
                engine.tap(float(center[0]), float(center[1]))
                step_log.append(f"Step {step}: Tapped '{label or action_key}'")
                time.sleep(0.6)
            elif action_key in ("scroll_down", "scroll_up"):
                direction = "down" if action_key == "scroll_down" else "up"
                engine.execute_action({"type": "scroll", "direction": direction})
                step_log.append(f"Step {step}: Scrolled {direction}")
                time.sleep(0.5)
            elif action_key == "back":
                engine.helper.action("global", action="BACK")
                step_log.append(f"Step {step}: Pressed Back")
                time.sleep(0.6)
            elif action_key == "wait":
                step_log.append(f"Step {step}: Waited 1.5s")
                time.sleep(1.5)
            else:
                step_log.append(f"Step {step}: {action_key}")
                time.sleep(0.5)

            if is_goal_met:
                print(f"✅ [agentdroid:ai] Goal satisfied! '{goal}'")
                is_success = True
                break

        client.close()

        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "ok": is_success,
                        "goal": goal,
                        "model": model,
                        "steps": len(history),
                        "history": history,
                    },
                    indent=2,
                )
            )

        return 0 if is_success or len(history) > 0 else 1
    finally:
        if getattr(args, "stop_after", False) and getattr(args, "launch", None):
            pkg = str(args.launch).split("/")[0]
            adb.stop_app(pkg)
        if watcher is not None:
            time.sleep(0.5)
            watcher.stop(force=True)
