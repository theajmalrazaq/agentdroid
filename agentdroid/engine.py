"""Artemis-derived Android Driving Engine for AgentDroid.

Provides high-precision indexed perception, dynamic-first coordinate-fallback
locating, action bursts, resilient scroll-and-find, and system dialog handling.
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
        fg = str(ui.get("foreground") or "").lower()

        # If systemui or packageinstaller is in foreground, dismiss permission/alert
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

    def execute_action_burst(self, actions: list[str]) -> list[dict[str, Any]]:
        """Execute a fast action burst (rapid multi-action execution) without LLM turn latency.

        Supported step syntax:
          - 'click:<selector_or_#id>'
          - 'tap:<x>,<y>'
          - 'tap_pct:<x_pct>,<y_pct>'
          - 'fill:<selector>=<text>'
          - 'type:<text>'
          - 'key:<KEYCODE>'
          - 'scroll:down' or 'scroll:up'
          - 'scroll-to:<text>'
          - 'swipe:<x1>,<y1>,<x2>,<y2>'
          - 'sleep:<seconds>'
          - 'dismiss' (auto dismiss dialogs)
        """
        results = []
        for act in actions:
            act = act.strip()
            if not act:
                continue

            verb, _, arg = act.partition(":")
            verb = verb.strip().lower()
            arg = arg.strip()

            if verb == "click":
                res = self.helper.tap_element(arg)
                results.append({"step": act, "result": res})
            elif verb == "tap":
                parts = [float(p.strip()) for p in arg.split(",") if p.strip()]
                if len(parts) >= 2:
                    res = self.tap(parts[0], parts[1])
                    results.append({"step": act, "result": res})
            elif verb == "tap_pct":
                parts = [float(p.strip()) for p in arg.split(",") if p.strip()]
                if len(parts) >= 2:
                    res = self.tap_percentage(parts[0], parts[1])
                    results.append({"step": act, "result": res})
            elif verb == "fill":
                sel, _, val = arg.partition("=")
                res = self.helper.fill_element(sel.strip(), val)
                results.append({"step": act, "result": res})
            elif verb == "type":
                res = self.helper.action("type", text=arg)
                results.append({"step": act, "result": res})
            elif verb == "key":
                res = self.helper.action("key", key=arg)
                results.append({"step": act, "result": res})
            elif verb == "scroll":
                res = self.helper.scroll(direction=arg or "down")
                results.append({"step": act, "result": res})
            elif verb == "scroll-to":
                res = self.scroll_and_find(arg)
                results.append({"step": act, "result": res})
            elif verb == "swipe":
                pts = [float(p.strip()) for p in arg.split(",") if p.strip()]
                if len(pts) >= 4:
                    res = self.swipe(pts[0], pts[1], pts[2], pts[3])
                    results.append({"step": act, "result": res})
            elif verb in ("sleep", "wait"):
                dur = float(arg) if arg else 0.5
                time.sleep(min(dur, 10.0))
                results.append({"step": act, "duration": dur})
            elif verb in ("dismiss", "auto-dismiss"):
                res = self.auto_dismiss_dialogs()
                results.append({"step": act, "result": res})
            else:
                results.append({"step": act, "error": f"Unknown action verb '{verb}'"})

            time.sleep(0.1)

        return results
