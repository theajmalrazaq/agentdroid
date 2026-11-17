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
    # ANRs, crashes, and first-run setup wizards
    "Wait",
    "Close app",
    "OK",
    "Dismiss",
    "Cancel",
    "Got it",
    "Not now",
    "Skip",
    "Continue",
    "Accept",
    "Finish",
    "Get started",
]


def _split_wait_timeout(arg: str) -> tuple[str, float | None]:
    """Extract optional trailing '@<seconds>' timeout from wait-* step arguments."""
    if "@" in arg:
        head, tail = arg.rsplit("@", 1)
        tail_s = tail.strip()
        try:
            secs = float(tail_s)
            if secs > 0:
                return head.strip(), secs
        except ValueError:
            pass
    return arg, None


def parse_do_step(step_str: str) -> dict[str, Any]:
    """Parse a compact `--do` or burst step string into a structured action dictionary.

    Examples:
      - 'click:Login' or 'click:#3' -> {"type": "click", "selector": "Login"}
      - 'tap:540,960' -> {"type": "tap", "x": 540.0, "y": 960.0}
      - 'tap_pct:50,40' -> {"type": "tap_pct", "x": 50.0, "y": 40.0}
      - 'fill:Email=user@test.com' -> {"type": "fill", "selector": "Email", "text": "user@test.com"}
      - 'type:hello' -> {"type": "type", "text": "hello"}
      - 'append:more' -> {"type": "type", "text": "more", "append": True}
      - 'scroll:down' -> {"type": "scroll", "direction": "down"}
      - 'scroll-to:About' -> {"type": "scroll_to", "text": "About"}
      - 'wait-text:Loaded' -> {"type": "wait_text", "text": "Loaded"}
      - 'wait-any:Loaded|Error|Skip' -> {"type": "wait_any", "patterns": ["Loaded", "Error", "Skip"]}
      - 'wait-gone:Loading' -> {"type": "wait_gone", "text": "Loading"}
      - 'wait-stable' -> {"type": "wait_stable"}
      - 'if-visible:Allow->click:Allow' -> {"type": "if_visible", "needle": "Allow", "step": {"type": "click", "selector": "Allow"}}
      - 'capture:val=Total: ([^\\s]+)' -> {"type": "capture", "var": "val", "pattern": "Total: ([^\\s]+)"}
      - 'hide-keyboard' -> {"type": "hide_keyboard"}
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
        if v in ("wait-stable", "wait_stable"):
            return {"type": "wait_stable"}
        if v.startswith(("wait-stable@", "wait_stable@")):
            _, to = _split_wait_timeout(raw)
            out: dict[str, Any] = {"type": "wait_stable"}
            if to is not None:
                out["timeout"] = to
            return out
        if v in ("wait-change", "wait_change"):
            return {"type": "wait_change"}
        if v.startswith(("wait-change@", "wait_change@")):
            _, to = _split_wait_timeout(raw)
            out: dict[str, Any] = {"type": "wait_change"}
            if to is not None:
                out["timeout"] = to
            return out
        if v in ("hide-keyboard", "hide_keyboard", "hide-ime", "hide_ime"):
            return {"type": "hide_keyboard"}
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
    if v == "append":
        return {"type": "type", "text": arg, "append": True}
    if v == "scroll":
        return {"type": "scroll", "direction": arg or "down"}
    if v in ("scroll-to", "scroll_to"):
        return {"type": "scroll_to", "text": arg}
    if v in ("wait", "wait-text", "wait_text"):
        txt, to = _split_wait_timeout(arg)
        out = {"type": "wait_text", "text": txt}
        if to is not None:
            out["timeout"] = to
        return out
    if v in ("wait-any", "wait_any"):
        raw_pats, to = _split_wait_timeout(arg)
        pats = [p.strip() for p in raw_pats.split("|") if p.strip()]
        out = {"type": "wait_any", "patterns": pats}
        if to is not None:
            out["timeout"] = to
        return out
    if v in ("wait-gone", "wait_gone"):
        txt, to = _split_wait_timeout(arg)
        out = {"type": "wait_gone", "text": txt}
        if to is not None:
            out["timeout"] = to
        return out
    if v in ("wait-stable", "wait_stable"):
        _, to = _split_wait_timeout(arg)
        if to is None and arg.strip():
            try:
                to = float(arg.strip())
            except ValueError:
                pass
        out = {"type": "wait_stable"}
        if to is not None:
            out["timeout"] = to
        return out
    if v in ("wait-change", "wait_change"):
        _, to = _split_wait_timeout(arg)
        if to is None and arg.strip():
            try:
                to = float(arg.strip())
            except ValueError:
                pass
        out = {"type": "wait_change"}
        if to is not None:
            out["timeout"] = to
        return out
    if v in ("hide-keyboard", "hide_keyboard", "hide-ime", "hide_ime"):
        return {"type": "hide_keyboard"}
    if v in ("if-visible", "if_visible", "if-missing", "if_missing"):
        if "->" not in arg:
            raise ValueError(f"{v} requires 'NEEDLE->STEP', got {raw!r}")
        needle, inner_step = arg.split("->", 1)
        return {
            "type": "if_missing" if "missing" in v else "if_visible",
            "needle": needle.strip(),
            "step": parse_do_step(inner_step.strip()),
        }
    if v in ("capture", "extract"):
        if "=" not in arg:
            raise ValueError(f"{v} requires 'VAR=REGEX', got {raw!r}")
        var_name, pattern = arg.split("=", 1)
        return {"type": "capture", "var": var_name.strip(), "pattern": pattern, "all": False}
    if v in ("capture-all", "capture_all", "extract-all", "extract_all"):
        if "=" not in arg:
            raise ValueError(f"{v} requires 'VAR=REGEX', got {raw!r}")
        var_name, pattern = arg.split("=", 1)
        return {"type": "capture", "var": var_name.strip(), "pattern": pattern, "all": True}
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
        self.vars: dict[str, str] = {}
        self.locked_app_package: str | None = None
        self._last_ui_blob: str | None = None

    def render_vars(self, val: Any) -> Any:
        if isinstance(val, str):
            if "{{" not in val or not self.vars:
                return val
            rendered = val
            for k, v in self.vars.items():
                rendered = rendered.replace(f"{{{{{k}}}}}", v)
            return rendered
        if isinstance(val, list):
            return [self.render_vars(x) for x in val]
        if isinstance(val, dict):
            return {k: self.render_vars(v) for k, v in val.items()}
        return val

    def get_screen_data(self, *, max_elements: int = 100, include_ime: bool = False) -> dict[str, Any]:
        """Capture screen hierarchy and return structured, numbered indexed elements."""
        ui = self.helper.dump_compact_ui(max_elements=max_elements, include_ime=include_ime)
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

    def auto_dismiss_dialogs(self, max_attempts: int = 6) -> dict[str, Any]:
        """Detect and dismiss common system permission dialogs, crash alerts, ANRs, and intro slides."""
        dismissed = []
        last_fg = None
        for _ in range(max_attempts):
            ui = self.helper.dump_compact_ui(max_elements=40)
            last_fg = ui.get("foreground")
            hit = False
            for target in SYSTEM_DIALOG_DISMISS_TARGETS:
                el = self.helper.find_element(target, max_elements=40)
                if el is not None:
                    cx, cy = el["center"]
                    res = self.helper.action("tap", x=float(cx), y=float(cy))
                    if res.get("success", True):
                        dismissed.append({"target": target, "center": [cx, cy]})
                        hit = True
                        time.sleep(0.35)
                        break
            if not hit:
                break

        return {
            "dismissed": dismissed,
            "count": len(dismissed),
            "foreground": last_fg,
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
        """Tap screen by percentage (0.0 to 100.0) scaled dynamically to active display size."""
        w, h = self.helper.get_display_size()
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
        act = self.render_vars(act)
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
            raw_text = str(act["text"])
            timeout = float(act.get("timeout", 25.0))
            if "|" in raw_text:
                pats = [p.strip() for p in raw_text.split("|") if p.strip()]
                wres = self.wait_condition("any", pats, timeout=timeout)
                return {"success": wres["success"], "text": raw_text, "matched": wres.get("matched")}
            ok = self._wait_for_text(raw_text, timeout=timeout)
            return {"success": ok, "text": raw_text}

        if act_type in ("wait_any", "wait-any"):
            pats = [str(p) for p in (act.get("patterns") or []) if str(p).strip()]
            return self.wait_condition("any", pats, timeout=float(act.get("timeout", 25.0)))

        if act_type in ("wait_gone", "wait-gone"):
            return self.wait_condition("gone", [str(act["text"])], timeout=float(act.get("timeout", 25.0)))

        if act_type in ("wait_stable", "wait-stable"):
            return self.wait_condition("stable", [], timeout=float(act.get("timeout", 15.0)))

        if act_type in ("wait_change", "wait-change"):
            return self.wait_condition(
                "change",
                [],
                timeout=float(act.get("timeout", 10.0)),
                prev_sig=self._last_ui_blob or getattr(self.helper, "_last_ui_blob", None),
            )

        if act_type in ("if_visible", "if-visible", "if_missing", "if-missing"):
            needle_raw = str(act.get("needle") or "")
            needles = [n.strip().lower() for n in needle_raw.split("|") if n.strip()]
            ui = self.helper.dump_compact_ui(max_elements=100, allow_sparse_fallback=False)
            blob = self._elements_search_blob(ui.get("elements") or [])
            present = any(n in blob for n in needles)
            should_run = (not present) if "missing" in act_type else present
            if should_run:
                inner_res = self.execute_action(dict(act["step"]))
                return {"matched": True, "needle": act["needle"], **inner_res}
            return {"success": True, "matched": False, "skipped": True, "needle": act.get("needle")}

        if act_type in ("capture", "extract"):
            var_name = str(act["var"])
            pattern = str(act["pattern"])
            capture_all = bool(act.get("all", False))
            ui = self.helper.dump_compact_ui(max_elements=120)
            texts: list[str] = []
            for el in ui.get("elements") or []:
                for field in ("full_text", "label", "desc"):
                    v = str(el.get(field) or "").strip()
                    if v and v not in texts:
                        texts.append(v)
            rx = re.compile(pattern, re.IGNORECASE)
            matches: list[str] = []
            for txt in texts:
                for m in rx.finditer(txt):
                    val = m.group(1) if rx.groups >= 1 and m.group(1) is not None else m.group(0)
                    val = val.strip()
                    if val and val not in matches:
                        matches.append(val)
                        if not capture_all:
                            break
                if matches and not capture_all:
                    break
            if not matches:
                return {"success": False, "var": var_name, "error": f"Pattern {pattern!r} matched nothing"}
            captured = "\n".join(matches) if capture_all else matches[0]
            self.vars[var_name] = captured
            return {"success": True, "var": var_name, "value": captured, "match_count": len(matches)}

        if act_type in ("hide_keyboard", "hide-keyboard"):
            shown = self.adb.shell("dumpsys input_method 2>/dev/null | grep -o 'mInputShown=[a-z]*' || true", timeout=2.0)
            if "mInputShown=true" in shown or not shown:
                self.helper.action("global", action="ESCAPE")
            return {"success": True, "action": "hide_keyboard"}

        if act_type == "key":
            return self.helper.action("global", action=str(act["key"]))

        if act_type == "open_url":
            uri_str = str(act["uri"])
            pkg = act.get("package")
            if not pkg and self.locked_app_package and not uri_str.startswith(("file://", "/")):
                pkg = self.locked_app_package
            res = self.adb.open_url(uri_str, package=pkg)
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
            time.sleep(0.02)
        return results

    @staticmethod
    def _elements_search_blob(elements: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for el in elements:
            for k in ("full_text", "label", "desc", "resource_id"):
                v = el.get(k)
                if v:
                    parts.append(str(v))
        return "\n".join(parts).lower()

    def _can_use_rust_wait(self) -> bool:
        return (
            isinstance(self.adb, AdbDevice)
            and self.adb._use_rust_adb()
            and getattr(self.helper.dump_compact_ui, "__func__", None)
            is AccessibilityHelperClient.dump_compact_ui
            and getattr(self.helper.ping, "__func__", None) is AccessibilityHelperClient.ping
        )

    def wait_condition(
        self,
        mode: str,
        patterns: list[str],
        *,
        timeout: float = 25.0,
        prev_sig: str | None = None,
    ) -> dict[str, Any]:
        """Adaptive non-blocking wait supporting modes: 'any', 'all', 'gone', 'stable', 'change'."""
        if self._can_use_rust_wait():
            try:
                from agentdroid import rust_bridge

                self.helper.ensure_ready()
                res = rust_bridge.wait_condition(
                    self.adb.serial,
                    self.helper._token,
                    mode=mode,
                    patterns=patterns,
                    timeout_sec=timeout,
                )
                if res is not None:
                    return res
            except Exception:
                pass

        needles = [p.strip().lower() for p in patterns if p.strip()]
        started = time.monotonic()
        deadline = started + max(0.2, timeout)
        prev_sig_val: str | None = None
        initial_sig: str | None = prev_sig if mode == "change" else None
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - started
            ui = self.helper.dump_compact_ui(
                max_elements=100,
                allow_sparse_fallback=(elapsed >= 1.5),
            )
            els = ui.get("elements") or []
            blob = self._elements_search_blob(els)
            if mode == "change":
                if initial_sig is None:
                    if els:
                        initial_sig = blob
                elif blob != initial_sig:
                    self._last_ui_blob = blob
                    return {"success": True, "elapsed_sec": round(elapsed, 2), "ui": ui}
            elif mode == "gone":
                if els and not any(n in blob for n in needles):
                    self._last_ui_blob = blob
                    return {"success": True, "elapsed_sec": round(elapsed, 2), "ui": ui}
            elif mode == "stable":
                if els and prev_sig_val == blob:
                    self._last_ui_blob = blob
                    return {"success": True, "elapsed_sec": round(elapsed, 2), "ui": ui}
                prev_sig_val = blob if els else None
            elif mode == "all":
                if all(n in blob for n in needles):
                    self._last_ui_blob = blob
                    return {"success": True, "elapsed_sec": round(elapsed, 2), "ui": ui}
            else:
                for idx, n in enumerate(needles):
                    if n in blob:
                        self._last_ui_blob = blob
                        return {
                            "success": True,
                            "matched": patterns[idx],
                            "elapsed_sec": round(elapsed, 2),
                            "ui": ui,
                        }
            time.sleep(0.05)
        return {"success": False, "elapsed_sec": round(time.monotonic() - started, 2)}

    def _wait_for_text(self, text_needle: str, timeout: float = 25.0) -> bool:
        if "|" in text_needle:
            pats = [p.strip() for p in text_needle.split("|") if p.strip()]
            return bool(self.wait_condition("any", pats, timeout=timeout).get("success"))
        if self._can_use_rust_wait():
            return bool(self.wait_condition("any", [text_needle], timeout=timeout).get("success"))
        needle = text_needle.lower()
        started = time.monotonic()
        deadline = started + timeout
        while time.monotonic() < deadline:
            elapsed = time.monotonic() - started
            ui = self.helper.dump_compact_ui(
                max_elements=100,
                allow_sparse_fallback=(elapsed >= 1.5),
            )
            blob = json.dumps(ui.get("elements", []), ensure_ascii=False).lower()
            if needle in blob:
                return True
            time.sleep(0.2)
        return False
