"""TypeSafe AI (Jev System One) integration for AgentDroid.

Provides sub-second, typed, calibrated autonomous decision-making over Android UI states.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
import urllib.error
from typing import Any

logger = logging.getLogger("agentdroid.typesafe")

DEFAULT_TYPESAFE_API_KEY = os.environ.get("TYPESAFE_API_KEY", "")
TYPESAFE_BASE_URL = os.environ.get("TYPESAFE_BASE_URL", "https://api.typesafe.ai/v1")


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

    def is_valid(self) -> bool:
        """Verify API key authentication against /models endpoint."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except Exception:
            return False

    def list_models(self) -> list[dict[str, Any]]:
        """List available TypeSafe models."""
        req = urllib.request.Request(
            f"{self.base_url}/models",
            headers={"Authorization": f"Bearer {self.api_key}"},
        )
        with urllib.request.urlopen(req, timeout=5.0) as resp:
            data = json.loads(resp.read().decode())
            return data.get("models", [])

    def decide(
        self,
        state: str | dict[str, Any],
        questions: dict[str, Any],
        model: str = "jev-latest",
        *,
        timeout: float = 10.0,
    ) -> dict[str, Any]:
        """Execute a System One decision call against /systemone."""
        payload = {
            "model": model,
            "state": state if isinstance(state, str) else json.dumps(state, ensure_ascii=False),
            "questions": questions,
        }
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/systemone",
            data=data,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            elapsed = time.perf_counter() - t0
            res = json.loads(raw)
            res["latency_ms"] = round(elapsed * 1000, 1)
            return res

    def rank_next_action(
        self,
        ui: dict[str, Any],
        goal: str,
        *,
        max_candidates: int = 30,
        model: str = "jev-latest",
    ) -> dict[str, Any]:
        """Rank clickable UI elements against a target goal using Jev's choice criteria."""
        elements = ui.get("elements") or []
        candidates: dict[str, str] = {}

        # Prioritize app interactive elements over background system UI
        app_elements: list[dict[str, Any]] = []
        sysui_elements: list[dict[str, Any]] = []
        for el in elements:
            pkg = el.get("package", "")
            if pkg == "com.android.systemui" or "systemui" in str(pkg).lower():
                sysui_elements.append(el)
            else:
                app_elements.append(el)

        ordered = app_elements + sysui_elements

        # Filter and index interactable candidates
        for el in ordered:
            clickable = el.get("clickable", False)
            cls = el.get("class", "Element")
            eid = el.get("id")
            lbl = el.get("label") or el.get("desc") or el.get("resource_id")
            if not lbl:
                continue
            if not clickable and cls in (
                "TextView",
                "ImageView",
                "LinearLayout",
                "RelativeLayout",
                "ViewGroup",
                "FrameLayout",
            ):
                continue
            candidates[f"tap_{eid}"] = f"Tap '{lbl}' ({cls})"
            if len(candidates) >= max_candidates:
                break

        candidates["wait"] = "Wait or screen is still loading"
        candidates["back"] = "Navigate back"

        state_text = (
            f"Foreground: {ui.get('foreground')}\n"
            f"UI Summary:\n{ui.get('formatted_text', '')}\n"
            f"Goal: {goal}"
        )

        questions = {
            "selected_action": {
                "type": "choice",
                "instructions": f"Which action directly achieves or progresses toward: '{goal}'?",
                "criteria": candidates,
            },
            "is_goal_met": {
                "type": "noul",
                "instructions": f"Has the goal '{goal}' already been completely fulfilled on this screen?",
            },
        }

        res = self.decide(state_text, questions, model=model)
        answers = res.get("answers", {})
        action_choice = answers.get("selected_action", {})
        goal_met_score = answers.get("is_goal_met", {}).get("noul", 0.0)

        picked_key = action_choice.get("choice", "wait")
        confidence = action_choice.get("confidence", 0.0)

        matched_element = None
        if picked_key.startswith("tap_"):
            try:
                target_id = int(picked_key.split("_")[1])
                matched_element = next((e for e in elements if e.get("id") == target_id), None)
            except Exception:
                pass

        return {
            "action_key": picked_key,
            "confidence": confidence,
            "is_goal_met": goal_met_score >= 0.70,
            "goal_met_probability": goal_met_score,
            "matched_element": matched_element,
            "probabilities": action_choice.get("probabilities", {}),
            "latency_ms": res.get("latency_ms", 0.0),
        }
