"""Artemis-derived Android Driving Engine for AgentDroid.

Provides high-precision indexed perception, dynamic-first coordinate-fallback
locating, action bursts, resilient scroll-and-find, and system dialog handling.
Single source of truth for UI action parsing and execution.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

from agentdroid.adb import AdbDevice
from agentdroid.helper import AccessibilityHelperClient

logger = logging.getLogger(__name__)

# Standard Android system dialog dismissal selectors & buttons
SYSTEM_DIALOG_DISMISS_TARGETS = [
    # Runtime permissions (Android 10 - 16)
    "While using the app",
    "Only this time",
    "Allow",
    "Grant",
    # ANRs and crashes
    "Wait",
    "Close app",
    "OK",
    "Dismiss",
    "Cancel",
    "Got it",
    "Not now",
]


def parse_do_step(step_str: str) -> dict[str, Any]:
    """Parse a compact `--do` or burst step string into a structured action dictionary.

    Examples:
      - 'click:Login' or 'click:#3' -> {"type": "click", "selector": "Login"}
      - 'tap:540,960' -> {"type": "tap", "x": 540.0, "y": 960.0}
      - 'tap_pct:50,40' -> {"type": "tap_pct", "x": 50.0, "y": 40.0}
      - 'fill:Email=user@test.com' -> {"type": "fill", "selector": "Email", "text": "user@test.com"}
      - 'type:hello' -> {"type": "type", "text": "hello"}
      - 'scroll:down' -> {"type": "scroll", "direction": "down"}
      - 'scroll-to:About' -> {"type": "scroll_to", "text": "About"}
      - 'swipe:100,500,100,200' -> {"type": "swipe", "x1": 100.0, "y1": 500.0, "x2": 100.0, "y2": 200.0}
      - 'key:BACK' -> {"type": "key", "key": "BACK"}
      - 'sleep:1.5' -> {"type": "sleep", "seconds": 1.5}
      - 'dismiss' -> {"type": "dismiss"}
    """
    raw = step_str.strip()
    if ":" not in raw:
        v = raw.lower()
        if v in ("dismiss", "auto-dismiss", "auto_dismiss"):
            return {"type": "dismiss"}
        return {"type": "click", "selector": raw}

    verb, arg = raw.split(":", 1)
    v = verb.strip().lower()
    arg = arg.strip()

    if v in ("click", "tap-text", "tap_text"):
        return {"type": "click", "selector": arg}
    if v == "tap":
        parts = [p.strip() for p in arg.split(",") if p.strip()]
        return {"type": "tap", "x": float(parts[0]), "y": float(parts[1])}
    if v in ("tap_pct", "tap-pct", "tap_percentage"):
        parts = [p.strip() for p in arg.split(",") if p.strip()]
        return {"type": "tap_pct", "x": float(parts[0]), "y": float(parts[1])}
    if v in ("fill", "input"):
        if "=" in arg:
            sel, txt = arg.split("=", 1)
            return {"type": "fill", "selector": sel.strip(), "text": txt}
        return {"type": "type", "text": arg}
    if v == "type":
        return {"type": "type", "text": arg}
    if v == "scroll":
        return {"type": "scroll", "direction": arg or "down"}
    if v in ("scroll-to", "scroll_to"):
        return {"type": "scroll_to", "text": arg}
    if v in ("wait", "wait-text", "wait_text"):
        return {"type": "wait_text", "text": arg}
    if v == "swipe":
        pts = [float(p.strip()) for p in arg.split(",") if p.strip()]
        return {
            "type": "swipe",
            "x1": pts[0],
            "y1": pts[1],
            "x2": pts[2],
            "y2": pts[3],
            "duration": int(pts[4]) if len(pts) > 4 else 300,
        }
    if v == "key":
        return {"type": "key", "key": arg}
    if v in ("open", "url", "open-url", "open_url"):
        return {"type": "open_url", "uri": arg}
    if v == "launch":
        return {"type": "launch", "package": arg}
    if v == "shell":
        return {"type": "shell", "cmd": arg}
    if v in ("sleep", "pause"):
        return {"type": "sleep", "seconds": float(arg or 1.0)}
    if v in ("dismiss", "auto-dismiss", "auto_dismiss"):
        return {"type": "dismiss"}
    return {"type": "click", "selector": raw}


class AndroidEngine:
    """Artemis-grade mobile automation controller for Claude Code, Codex, Antigravity, and Cursor."""

    def __init__(self, adb: AdbDevice | None = None) -> None:
        self.adb = adb or AdbDevice()
        self.helper = AccessibilityHelperClient(self.adb)

    def get_screen_data(self, *, max_elements: int = 100) -> dict[str, Any]:
        """Capture screen hierarchy and return structured, numbered indexed elements."""
        ui = self.helper.dump_compact_ui(max_elements=max_elements)
        elements = ui.get("elements") or []

        # Build Artemis-style minimal readable list for AI agents
        formatted_lines = []
        for el in elements:
            idx = el.get("id")
            label = el.get("label", "")
            cls = el.get("class", "")
            center = el.get("center", [0, 0])
            desc = el.get("desc")
            res_id = el.get("resource_id")

            parts = [f"[#{idx}]", f"{cls}: '{label}'" if label else cls]
            if desc and desc != label:
                parts.append(f"Desc: '{desc}'")
            if res_id:
                parts.append(f"ID: {res_id}")
            parts.append(f"Center: ({center[0]}, {center[1]})")
            formatted_lines.append(" | ".join(parts))

        ui["formatted_text"] = "\n".join(formatted_lines)
        return ui

    def auto_dismiss_dialogs(self) -> dict[str, Any]:
        """Detect and dismiss common system permission dialogs, crash alerts, or ANRs."""
        ui = self.helper.dump_compact_ui(max_elements=40)
        dismissed = []
        for target in SYSTEM_DIALOG_DISMISS_TARGETS:
            el = self.helper.find_element(target, max_elements=40)
            if el is not None:
                cx, cy = el["center"]
                res = self.helper.action("tap", x=float(cx), y=float(cy))
                if res.get("success", True):
                    dismissed.append({"target": target, "center": [cx, cy]})
                    time.sleep(0.3)
                    break

        return {
            "dismissed": dismissed,
            "count": len(dismissed),
            "foreground": ui.get("foreground"),
        }

    def tap(
        self,
        x: float,
        y: float,
        *,
        times: int = 1,
        delay_ms: int = 100,
    ) -> dict[str, Any]:
        """Direct coordinate tap with repeat support."""
        for i in range(times):
            res = self.helper.action("tap", x=float(x), y=float(y))
            if i < times - 1 and delay_ms > 0:
                time.sleep(delay_ms / 1000.0)
        return {"action": "tap", "x": x, "y": y, "times": times, "success": True}

    def tap_percentage(self, x_percent: float, y_percent: float) -> dict[str, Any]:
        """Tap screen by percentage (0.0 to 100.0)."""
        w, h = 1080, 2400
        x = round((x_percent / 100.0) * w)
        y = round((y_percent / 100.0) * h)
        return self.tap(x, y)

    def swipe(
        self,
        start_x: float,
        start_y: float,
        end_x: float,
        end_y: float,
        duration_ms: int = 300,
    ) -> dict[str, Any]:
        """Swipe or drag between coordinates."""
        res = self.helper.action(
            "swipe",
            start_x=float(start_x),
            start_y=float(start_y),
            end_x=float(end_x),
            end_y=float(end_y),
            duration_ms=int(duration_ms),
        )
        return {
            "action": "swipe",
            "from": [start_x, start_y],
            "to": [end_x, end_y],
            "duration_ms": duration_ms,
            "success": bool(res.get("success", True)),
        }

    def scroll_and_find(
        self,
        target: str,
        *,
        direction: str = "down",
        max_scrolls: int = 8,
    ) -> dict[str, Any]:
        """Artemis active exploration: scroll until element is visible, then return its location."""
        return self.helper.scroll_to_text(target, max_scrolls=max_scrolls, direction=direction)

    def execute_action(self, act: dict[str, Any]) -> dict[str, Any]:
        """Single source of truth for executing any structured mobile UI action."""
        act_type = str(act.get("type") or act.get("cmd") or "").lower()

        if act_type in ("click", "tap_text", "tap-text"):
            return self.helper.tap_element(str(act["selector"]))

        if act_type == "fill":
            return self.helper.fill_element(
                str(act["selector"]),
                str(act["text"]),
                submit=bool(act.get("submit", False)),
            )

        if act_type == "tap":
            return self.tap(float(act["x"]), float(act["y"]))

        if act_type in ("tap_pct", "tap-pct", "tap_percentage"):
            return self.tap_percentage(float(act["x"]), float(act["y"]))

        if act_type == "type":
            return self.helper.action("type", text=str(act["text"]), append=bool(act.get("append", False)))

        if act_type == "swipe":
            return self.swipe(
                float(act["x1"]),
                float(act["y1"]),
                float(act["x2"]),
                float(act["y2"]),
                duration_ms=int(act.get("duration", 300)),
            )

        if act_type == "scroll":
            return self.helper.scroll(str(act.get("direction", "down")))

        if act_type in ("scroll_to", "scroll-to"):
            return self.scroll_and_find(str(act["text"]))

        if act_type in ("wait_text", "wait-text"):
            ok = self._wait_for_text(str(act["text"]), timeout=float(act.get("timeout", 15.0)))
            return {"success": ok, "text": act["text"]}

        if act_type == "key":
            return self.helper.action("global", action=str(act["key"]))

        if act_type == "open_url":
            res = self.adb.open_url(str(act["uri"]))
            return {"success": bool(res.get("opened", True)), **res}

        if act_type == "launch":
            res = self.adb.launch_app(str(act["package"]))
            return {"success": bool(res.get("launched", True)), **res}

        if act_type == "shell":
            out = self.adb.shell(str(act["cmd"]))
            return {"success": True, "output": out}

        if act_type in ("dismiss", "auto_dismiss", "auto-dismiss"):
            return {"success": True, **self.auto_dismiss_dialogs()}

        if act_type in ("sleep", "wait", "pause"):
            secs = float(act.get("seconds", 1.0))
            time.sleep(secs)
            return {"success": True, "slept": secs}

        return {"success": False, "error": f"Unknown action type: {act_type}"}

    def execute_action_burst(self, actions: list[str]) -> list[dict[str, Any]]:
        """Execute a fast action burst without LLM turn latency."""
        results = []
        for step in actions:
            step_str = step.strip()
            if not step_str:
                continue
            parsed = parse_do_step(step_str)
            res = self.execute_action(parsed)
            results.append({"step": step_str, "result": res})
            time.sleep(0.1)
        return results

    def _wait_for_text(self, text_needle: str, timeout: float = 15.0) -> bool:
        needle = text_needle.lower()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            ui = self.helper.dump_compact_ui(max_elements=100)
            blob = json.dumps(ui.get("elements", []), ensure_ascii=False).lower()
            if needle in blob:
                return True
            time.sleep(0.5)
        return False
