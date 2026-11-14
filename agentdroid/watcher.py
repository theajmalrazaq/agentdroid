"""Headless vs. Live Watch controller (scrcpy + Artemis SSE live action telemetry)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
import webbrowser
from typing import Any, Callable


def has_gui_display() -> bool:
    """Return True if the host environment has an active GUI display for scrcpy/browser."""
    if sys.platform in ("darwin", "win32"):
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


class LiveWatcher:
    """Manages silent background (--headless) vs live visual monitoring (--watch) of the AI agent."""

    def __init__(
        self,
        serial: str,
        *,
        artemis_url: str = "http://127.0.0.1:8000",
        watch: bool = False,
        prefer_web: bool = False,
        interactive_control: bool = False,
    ) -> None:
        self.serial = serial
        self.artemis_url = artemis_url.rstrip("/")
        self.watch = watch
        self.prefer_web = prefer_web
        self.interactive_control = interactive_control
        self._scrcpy_proc: subprocess.Popen | None = None
        self._sse_stop = threading.Event()
        self._sse_thread: threading.Thread | None = None

    def start(self, session_id: str | None = None) -> dict[str, Any]:
        """Start live visual watch if --watch is enabled; no-op in --headless mode."""
        if not self.watch:
            return {"mode": "headless", "viewer": None}

        viewer_used = "terminal_stream"
        scrcpy_bin = shutil.which("scrcpy")

        if has_gui_display() and scrcpy_bin and not self.prefer_web:
            cmd = [
                scrcpy_bin,
                "-s",
                self.serial,
                "--window-title",
                f"AgentDroid AI Live Watch ({self.serial})",
                "--stay-awake",
                "--no-audio",
            ]
            if not self.interactive_control:
                cmd.append("--no-control")
            try:
                self._scrcpy_proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                viewer_used = "scrcpy"
                print(
                    f"[agentdroid:watch] Live scrcpy window opened for {self.serial} (PID {self._scrcpy_proc.pid})",
                    file=sys.stderr,
                )
            except Exception as exc:
                print(f"[agentdroid:watch] Could not start scrcpy: {exc}", file=sys.stderr)

        elif has_gui_display() and self.prefer_web:
            try:
                webbrowser.open(self.artemis_url)
                viewer_used = "web_console"
                print(
                    f"[agentdroid:watch] Opened Artemis Live Console at {self.artemis_url}",
                    file=sys.stderr,
                )
            except Exception:
                pass
        else:
            print(
                f"[agentdroid:watch] Streaming live AI agent actions in terminal "
                f"(Live MJPEG stream also at {self.artemis_url}/api/stream/device-live)",
                file=sys.stderr,
            )

        if session_id:
            self.start_sse_stream(session_id)

        return {"mode": "watch", "viewer": viewer_used}

    def start_sse_stream(
        self,
        session_id: str = "active",
        *,
        as_jsonl: bool = False,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        """Subscribe to Artemis /api/stream/{session_id} and display live agent actions."""
        self._sse_stop.clear()

        def _reader() -> None:
            url = f"{self.artemis_url}/api/stream/{session_id}"
            req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
            try:
                with urllib.request.urlopen(req, timeout=600.0) as resp:
                    event_type = "message"
                    data_lines: list[str] = []
                    for raw_line in resp:
                        if self._sse_stop.is_set():
                            break
                        line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
                        if not line:
                            if data_lines:
                                payload_raw = "\n".join(data_lines)
                                data_lines.clear()
                                try:
                                    payload = json.loads(payload_raw)
                                except ValueError:
                                    payload = {"raw": payload_raw}
                                if on_event:
                                    on_event(event_type, payload)
                                else:
                                    self._print_live_event(event_type, payload, as_jsonl=as_jsonl)
                                if event_type == "session_ended":
                                    break
                            event_type = "message"
                        elif line.startswith("event:"):
                            event_type = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"):
                            data_lines.append(line.split(":", 1)[1].lstrip())
            except Exception:
                pass

        self._sse_thread = threading.Thread(target=_reader, daemon=True)
        self._sse_thread.start()

    def _print_live_event(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        as_jsonl: bool = False,
    ) -> None:
        if event_type in ("keep-alive", "info"):
            return
        if as_jsonl:
            print(json.dumps({"event": event_type, "data": payload}, ensure_ascii=False), flush=True)
            return

        if event_type == "session_started":
            goal = payload.get("initial_goal") or payload.get("goal") or ""
            profile = payload.get("profile") or "flash"
            print(f"[agentdroid:watch] ▶ Session started ({profile}): {goal}", file=sys.stderr)
        elif event_type == "startup_progress":
            msg = payload.get("message") or payload.get("stage") or ""
            if msg:
                print(f"[agentdroid:watch] ⚙ {msg}", file=sys.stderr)
        elif event_type in ("step_recorded", "agent_step", "action"):
            step_num = payload.get("step_number") or payload.get("step") or "?"
            action = (
                payload.get("action_type")
                or payload.get("tool_name")
                or payload.get("action")
                or "step"
            )
            thought = (
                payload.get("summary")
                or payload.get("thought")
                or payload.get("reasoning")
                or payload.get("description")
                or ""
            )
            print(f"[agentdroid:watch] [Step {step_num}] {action}: {thought}", file=sys.stderr)
        elif event_type == "session_ended":
            status = payload.get("status") or "done"
            print(f"[agentdroid:watch] ■ Session finished ({status})", file=sys.stderr)

    def stop(self) -> None:
        self._sse_stop.set()
        if self._scrcpy_proc is not None and self._scrcpy_proc.poll() is None:
            try:
                self._scrcpy_proc.terminate()
                self._scrcpy_proc.wait(timeout=3.0)
            except Exception:
                try:
                    self._scrcpy_proc.kill()
                except Exception:
                    pass
            self._scrcpy_proc = None
