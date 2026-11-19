"""TypeSafe AI (Jev System One) integration for AgentDroid.

Provides sub-second, typed, calibrated autonomous decision-making over Android UI states.
"""

from __future__ import annotations

import http.client
import json
import logging
import os
import re
import threading
import time
import urllib.parse
from typing import Any

logger = logging.getLogger("agentdroid.typesafe")

DEFAULT_TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
TYPESAFE_BASE_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")

_QUOTED_RE = re.compile(r"(?:^|[\s(:=])['\"]([^'\"]{1,120})['\"](?=$|[\s).,;:!?])")
_GENERIC_EDIT_LABELS = {"edittext", "edit text", ""}
_GENERIC_CONTAINER_CLASSES = {"LinearLayout", "RelativeLayout", "ViewGroup", "FrameLayout"}


def _infer_container_label(el: dict[str, Any], elements: list[dict[str, Any]]) -> str:
    """Resolve human-readable row text for clickable container layouts (RecyclerView/Settings rows)."""
    cy = (el.get("center") or [0, 0])[1]
    texts: list[str] = []
    for other in elements:
        if other.get("id") == el.get("id") or other.get("systemui"):
            continue
        other_cls = str(other.get("class") or "")
        if other_cls in _GENERIC_CONTAINER_CLASSES:
            continue
        olbl = str(other.get("label") or other.get("desc") or "").strip()
        if not olbl or olbl.lower() in _GENERIC_EDIT_LABELS:
            continue
        oy = (other.get("center") or [0, 0])[1]
        if abs(oy - cy) <= 75 and olbl not in texts:
            texts.append(olbl)
        if len(texts) >= 2:
            break
    return " — ".join(texts)


def extract_text_inputs(goal: str) -> list[str]:
    """Extract ordered unique quoted literal values from a task goal string."""
    seen: list[str] = []
    for match in _QUOTED_RE.finditer(goal):
        val = match.group(1)
        if val and val not in seen:
            seen.append(val)
    return seen


def _infer_field_hint(el: dict[str, Any], elements: list[dict[str, Any]]) -> str:
    """Resolve the best human-readable hint for an editable field using adjacent labels."""
    lbl = str(el.get("label") or "").strip()
    desc = str(el.get("desc") or "").strip()
    rid = str(el.get("resource_id") or "").strip()

    parts: list[str] = []
    if lbl and lbl.lower() not in _GENERIC_EDIT_LABELS:
        parts.append(lbl)
    if desc and desc not in parts:
        parts.append(desc)
    if rid and rid not in parts and rid.lower() not in _GENERIC_EDIT_LABELS:
        parts.append(f"[{rid}]")

    looks_like_id = (lbl == rid) or ("_" in lbl and " " not in lbl)
    if not parts or looks_like_id:
        cx, cy = (el.get("center") or [0, 0])[:2]
        best_dist = 180.0
        best_lbl = ""
        for other in elements:
            if other.get("id") == el.get("id") or other.get("systemui"):
                continue
            other_cls = str(other.get("class") or "")
            if other_cls not in ("TextView", "ImageView"):
                continue
            other_lbl = str(other.get("label") or other.get("desc") or "").strip()
            if not other_lbl or other_lbl.lower() in _GENERIC_EDIT_LABELS:
                continue
            ox, oy = (other.get("center") or [0, 0])[:2]
            dy = cy - oy
            if -35 <= dy <= 165 and abs(ox - cx) <= 600:
                dist = abs(dy) + abs(ox - cx) * 0.2
                if dist < best_dist:
                    best_dist = dist
                    best_lbl = other_lbl
        if best_lbl and best_lbl not in parts:
            parts.insert(0, best_lbl)

    if not parts:
        cy = (el.get("center") or [0, 0])[1]
        return f"input field at y={cy}"
    return " ".join(parts)


class TypeSafeAIClient:
    """Client for TypeSafe AI's Jev System One decision models."""

    def __init__(self, api_key: str | None = None, base_url: str = TYPESAFE_BASE_URL) -> None:
        key = api_key if api_key is not None else os.environ.get("TYPESAFE_API_KEY", DEFAULT_TYPESAFE_API_KEY)
        self.api_key = (key or "").strip()
        self.base_url = base_url.rstrip("/")
        if not self.api_key:
            raise ValueError(
                "TypeSafe AI API key is required. Pass api_key or set TYPESAFE_API_KEY environment variable."
            )
        parsed = urllib.parse.urlsplit(self.base_url)
        self._scheme = parsed.scheme or "https"
        self._host = parsed.netloc
        self._base_path = parsed.path.rstrip("/")
        self._conn_lock = threading.Lock()
        self._conn: http.client.HTTPConnection | None = None

    def _get_conn(self, timeout: float = 10.0) -> http.client.HTTPConnection:
        if self._conn is not None:
            self._conn.timeout = timeout
            return self._conn
        if self._scheme == "http":
            self._conn = http.client.HTTPConnection(self._host, timeout=timeout)
        else:
            self._conn = http.client.HTTPSConnection(self._host, timeout=timeout)
        return self._conn

    def _reset_conn(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except (OSError, http.client.HTTPException) as exc:
                logger.debug("TypeSafe connection close error: %s", exc)
            self._conn = None

    def _request_json(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any] | None = None,
        timeout: float = 10.0,
    ) -> tuple[int, dict[str, Any]]:
        path = f"{self._base_path}{endpoint}"
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8") if payload is not None else None
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Connection": "keep-alive",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"

        with self._conn_lock:
            last_exc: Exception | None = None
            for attempt in range(3):
                conn = self._get_conn(timeout=timeout)
                try:
                    conn.request(method, path, body=body, headers=headers)
                    resp = conn.getresponse()
                    raw = resp.read().decode("utf-8")
                    data = json.loads(raw) if raw else {}
                    return resp.status, data
                except (http.client.HTTPException, OSError) as exc:
                    last_exc = exc
                    self._reset_conn()
                    if attempt < 2:
                        time.sleep(0.5)
                        continue
                    raise
            raise RuntimeError(f"TypeSafe request failed: {last_exc}")

    def close(self) -> None:
        """Close the persistent HTTP keep-alive connection."""
        with self._conn_lock:
            self._reset_conn()

    def is_valid(self) -> bool:
        """Verify API key authentication against /models endpoint."""
        try:
            status, _ = self._request_json("GET", "/models", timeout=5.0)
            return status == 200
        except (OSError, http.client.HTTPException, ValueError, RuntimeError) as exc:
            logger.debug("TypeSafe key validation failed: %s", exc)
            return False

    def list_models(self) -> list[dict[str, Any]]:
        """List available TypeSafe models."""
        status, data = self._request_json("GET", "/models", timeout=5.0)
        if status >= 400:
            raise RuntimeError(f"TypeSafe /models error ({status}): {data}")
        return data.get("models", [])

    def decide(
        self,
        state: str | dict[str, Any],
        questions: dict[str, Any],
        model: str = "jev-latest",
        *,
        timeout: float = 20.0,
    ) -> dict[str, Any]:
        """Execute a System One decision call against /systemone."""
        payload = {
            "model": model,
            "state": state if isinstance(state, str) else json.dumps(state, ensure_ascii=False),
            "questions": questions,
        }
        t0 = time.perf_counter()
        status, res = self._request_json("POST", "/systemone", payload=payload, timeout=timeout)
        elapsed = time.perf_counter() - t0
        if status >= 400:
            raise RuntimeError(f"TypeSafe /systemone error ({status}): {res}")
        res["latency_ms"] = round(elapsed * 1000, 1)
        return res

    def rank_next_action(
        self,
        ui: dict[str, Any],
        goal: str,
        *,
        max_candidates: int = 45,
        model: str = "jev-latest",
        step_history: list[str] | None = None,
        text_inputs: list[str] | None = None,
    ) -> dict[str, Any]:
        """Rank actionable UI operations (tap, fill, scroll, back, wait, done) against a goal."""
        elements = ui.get("elements") or []
        candidates: dict[str, str] = {}
        fill_map: dict[str, tuple[dict[str, Any], str]] = {}

        inputs = list(text_inputs) if text_inputs is not None else extract_text_inputs(goal)
        history_text = "\n".join(step_history[-8:]) if step_history else "None yet"

        # Exclude noisy status-bar icons (y < 75 systemui) and calendar grid backgrounds
        app_elements: list[dict[str, Any]] = []
        sysui_elements: list[dict[str, Any]] = []
        for el in elements:
            pkg = str(el.get("package") or "")
            rid = str(el.get("resource_id") or "")
            lbl = str(el.get("label") or "")
            cy = (el.get("center") or [0, 0])[1]
            is_sys = bool(el.get("systemui")) or pkg == "com.android.systemui" or "systemui" in pkg.lower()
            if is_sys:
                if rid in ("clock", "battery") or cy < 80 or "accessibility helper" in lbl.lower():
                    continue
                sysui_elements.append(el)
            else:
                if rid == "month_view_background" or lbl == "month_view_background":
                    continue
                app_elements.append(el)

        ordered = app_elements + sysui_elements

        # Reserve slots for global navigation/scroll/terminal primitives
        max_element_slots = max(10, max_candidates - 5)

        for el in ordered:
            if len(candidates) >= max_element_slots:
                break
            clickable = bool(el.get("clickable", False))
            editable = bool(el.get("editable", False))
            cls = str(el.get("class") or "Element")
            eid = el.get("id")
            rid = str(el.get("resource_id") or "").strip()
            lbl = str(el.get("label") or el.get("desc") or rid or "").strip()

            is_edit = editable or cls == "EditText"
            if is_edit:
                hint = _infer_field_hint(el, elements)
                cur_val = lbl if (lbl and lbl.lower() not in _GENERIC_EDIT_LABELS) else ""
                if inputs:
                    for idx, val in enumerate(inputs):
                        if len(candidates) >= max_element_slots:
                            break
                        if cur_val and val in cur_val:
                            continue
                        already = f"Typed '{val}'" in history_text
                        if already:
                            continue
                        fkey = f"fill_{eid}_{idx}"
                        candidates[fkey] = f"Type '{val}' into '{hint}' (EditText)"
                        fill_map[fkey] = (el, val)
                else:
                    candidates[f"tap_{eid}"] = f"Focus '{hint}' (EditText)"
                continue

            if not clickable and cls in (
                "TextView",
                "ImageView",
                "LinearLayout",
                "RelativeLayout",
                "ViewGroup",
                "FrameLayout",
                "View",
            ):
                continue

            if clickable and cls in _GENERIC_CONTAINER_CLASSES and (not lbl or lbl in _GENERIC_CONTAINER_CLASSES):
                inferred = _infer_container_label(el, elements)
                if inferred:
                    lbl = inferred

            if not lbl:
                continue

            desc_tag = f" [{rid}]" if rid and rid != lbl else ""
            candidates[f"tap_{eid}"] = f"Tap '{lbl}'{desc_tag} ({cls})"

        candidates["scroll_down"] = "Scroll down to reveal more options or list items off-screen"
        candidates["scroll_up"] = "Scroll up to view earlier options"
        candidates["back"] = "Navigate back to previous screen"
        candidates["wait"] = "Wait 1.5s for UI loading, animation, or active timer/recording"
        candidates["done"] = "Task goal is already achieved on screen or via prior steps; finish now without undoing"

        # Build concise filtered UI summary excluding status bar icons
        filtered_lines: list[str] = []
        for el in ordered[:60]:
            el_idx = el.get("id")
            cls = el.get("class", "")
            lbl = el.get("label", "")
            rid = el.get("resource_id", "")
            cy = (el.get("center") or [0, 0])[1]
            hint = _infer_field_hint(el, elements) if cls == "EditText" else lbl
            parts = [f"[#{el_idx}]", f"{cls}: '{hint}'" if hint else cls]
            if rid and rid != hint:
                parts.append(f"ID:{rid}")
            parts.append(f"y={cy}")
            filtered_lines.append(" | ".join(parts))

        fg = ui.get("foreground") or {}
        state_text = (
            f"Goal: {goal}\n"
            f"Foreground: {fg.get('package')}/{fg.get('activity')}\n"
            f"Steps Executed So Far:\n{history_text}\n\n"
            f"Screen Elements ({len(filtered_lines)}):\n" + "\n".join(filtered_lines)
        )

        questions = {
            "selected_action": {
                "type": "choice",
                "instructions": f"Pick the single best next action toward accomplishing: '{goal}'. Avoid repeating actions that already succeeded unless needed.",
                "criteria": candidates,
            },
            "is_goal_met": {
                "type": "noul",
                "instructions": f"Has the full goal '{goal}' already been visibly completed and saved on screen?",
            },
        }

        res = self.decide(state_text, questions, model=model)
        answers = res.get("answers", {})
        action_choice = answers.get("selected_action", {})
        goal_met_score = answers.get("is_goal_met", {}).get("noul", 0.0)

        picked_key = action_choice.get("choice", "wait")
        confidence = action_choice.get("confidence", 0.0)

        matched_element = None
        fill_text = None
        action_type = picked_key

        if picked_key in fill_map:
            matched_element, fill_text = fill_map[picked_key]
            action_type = "fill"
        elif picked_key.startswith("tap_"):
            action_type = "tap"
            try:
                target_id = int(picked_key.split("_")[1])
                matched_element = next((e for e in elements if e.get("id") == target_id), None)
            except (ValueError, IndexError) as exc:
                logger.debug("Could not parse tap action index %r: %s", picked_key, exc)

        return {
            "action_key": picked_key,
            "action_type": action_type,
            "action_label": candidates.get(picked_key, ""),
            "fill_text": fill_text,
            "confidence": confidence,
            "is_goal_met": bool(goal_met_score >= 0.78 or picked_key == "done"),
            "goal_met_probability": goal_met_score,
            "matched_element": matched_element,
            "probabilities": action_choice.get("probabilities", {}),
            "latency_ms": res.get("latency_ms", 0.0),
        }
