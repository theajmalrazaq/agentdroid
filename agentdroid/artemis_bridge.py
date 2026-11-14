"""Bridge to Google Artemis HTTP Daemon & Standalone CLI with autonomous retry-until-output loop."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from typing import Any, Callable

from agentdroid.watcher import LiveWatcher


@dataclass
class GoalExecutionResult:
    """Normalized result of executing one or more natural-language Android goals via Artemis."""

    succeeded: bool
    status: str
    goal: str
    profile: str
    session_id: str
    output: Any = None
    explanation: str | None = None
    error: str | None = None
    attempts: int = 1
    duration_sec: float = 0.0
    steps_count: int = 0
    raw_session: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "succeeded": self.succeeded,
            "status": self.status,
            "goal": self.goal,
            "profile": self.profile,
            "session_id": self.session_id,
            "output": self.output,
            "explanation": self.explanation,
            "error": self.error,
            "attempts": self.attempts,
            "steps_count": self.steps_count,
            "duration_sec": round(self.duration_sec, 2),
        }


class ArtemisBridge:
    """Client for the Artemis Agent Controller (HTTP API + Standalone CLI fallback)."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        device_serial: str | None = None,
        default_profile: str = "flash",
    ) -> None:
        self.base_url = (
            base_url
            or os.environ.get("ARTEMIS_BASE_URL")
            or f"http://{os.environ.get('ARTEMIS_DAEMON_HOST', '127.0.0.1')}:{os.environ.get('ARTEMIS_PORT', '8000')}"
        ).rstrip("/")
        self.device_serial = device_serial
        self.default_profile = default_profile

    def _http_json(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float = 15.0,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "Accept": "application/json",
            "Origin": self.base_url,
        }
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}

    def is_daemon_online(self) -> bool:
        try:
            status = self._http_json("GET", "/api/status", timeout=3.0)
            return isinstance(status, dict) and "status" in status
        except Exception:
            return False

    def daemon_status(self) -> dict[str, Any]:
        try:
            return self._http_json("GET", "/api/status", timeout=5.0)
        except Exception as exc:
            return {"status": "offline", "error": str(exc), "base_url": self.base_url}

    def list_devices(self) -> list[dict[str, Any]]:
        try:
            res = self._http_json("GET", "/api/devices", timeout=5.0)
            devices = res.get("devices", [])
            return devices if isinstance(devices, list) else []
        except Exception:
            return []

    def execute_goal(
        self,
        goal: str,
        *,
        profile: str | None = None,
        expected_output: str | None = None,
        locked_app_package: str | None = None,
        app_path: str | None = None,
        verification_level: str | None = None,
        explorer_mode: str | None = None,
        timeout: float = 900.0,
        poll_interval: float = 1.5,
        watcher: LiveWatcher | None = None,
        until_output: bool = False,
        max_attempts: int = 1,
        ui_context_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> GoalExecutionResult:
        """Execute a natural-language goal on the device, retrying with screen context if until_output=True."""
        resolved_profile = (profile or self.default_profile or "flash").lower()
        effective_max = max(1, max_attempts if max_attempts > 1 else (3 if until_output else 1))
        started_all = time.monotonic()

        current_goal = goal
        last_result: GoalExecutionResult | None = None

        for attempt in range(1, effective_max + 1):
            res = self._execute_single_attempt(
                current_goal,
                profile=resolved_profile,
                expected_output=expected_output,
                locked_app_package=locked_app_package,
                app_path=app_path if attempt == 1 else None,
                verification_level=verification_level,
                explorer_mode=explorer_mode,
                timeout=timeout,
                poll_interval=poll_interval,
                watcher=watcher,
            )
            res.attempts = attempt
            res.duration_sec = time.monotonic() - started_all
            last_result = res

            has_required_output = True
            if expected_output and until_output:
                has_required_output = bool(res.output or res.explanation)

            if res.succeeded and has_required_output:
                return res

            if attempt < effective_max:
                ui_hint = ""
                if ui_context_provider is not None:
                    try:
                        ui_dump = ui_context_provider()
                        fg = ui_dump.get("foreground", {}).get("component") or "unknown"
                        labels = [
                            str(e.get("label"))
                            for e in ui_dump.get("elements", [])[:15]
                            if e.get("label")
                        ]
                        ui_hint = (
                            f" Current foreground is '{fg}' with visible elements: "
                            + ", ".join(labels)
                            + "."
                        )
                    except Exception:
                        pass
                prev_err = res.error or res.explanation or f"status={res.status}"
                current_goal = (
                    f"{goal}\n\n"
                    f"[Recovery Attempt {attempt + 1}/{effective_max}]: Previous attempt ended with "
                    f"({prev_err}).{ui_hint} Recover from the current screen state and complete "
                    f"the objective."
                )

        assert last_result is not None
        return last_result

    def _execute_single_attempt(
        self,
        goal: str,
        *,
        profile: str,
        expected_output: str | None,
        locked_app_package: str | None,
        app_path: str | None,
        verification_level: str | None,
        explorer_mode: str | None,
        timeout: float,
        poll_interval: float,
        watcher: LiveWatcher | None,
    ) -> GoalExecutionResult:
        started = time.monotonic()
        session_id = str(uuid.uuid4())

        if self.is_daemon_online():
            return self._execute_via_daemon(
                goal,
                session_id=session_id,
                profile=profile,
                expected_output=expected_output,
                locked_app_package=locked_app_package,
                app_path=app_path,
                verification_level=verification_level,
                explorer_mode=explorer_mode,
                timeout=timeout,
                poll_interval=poll_interval,
                watcher=watcher,
                started=started,
            )

        return self._execute_via_cli_fallback(
            goal,
            session_id=session_id,
            profile=profile,
            expected_output=expected_output,
            locked_app_package=locked_app_package,
            app_path=app_path,
            verification_level=verification_level,
            explorer_mode=explorer_mode,
            timeout=timeout,
            started=started,
        )

    def _execute_via_daemon(
        self,
        goal: str,
        *,
        session_id: str,
        profile: str,
        expected_output: str | None,
        locked_app_package: str | None,
        app_path: str | None,
        verification_level: str | None,
        explorer_mode: str | None,
        timeout: float,
        poll_interval: float,
        watcher: LiveWatcher | None,
        started: float,
    ) -> GoalExecutionResult:
        payload: dict[str, Any] = {
            "goal": goal,
            "profile": profile,
            "session_id": session_id,
            "ingress": "python_sdk",
            "enable_outputter": True if expected_output else None,
        }
        for key, val in (
            ("device_serial", self.device_serial),
            ("expected_output", expected_output),
            ("locked_app_package", locked_app_package),
            ("app_path", app_path),
            ("verification_level", verification_level),
            ("explorer_mode", explorer_mode),
        ):
            if val is not None:
                payload[key] = val

        resp = self._http_json("POST", "/api/run", payload, timeout=30.0)
        status = str(resp.get("status") or "unknown").lower()
        tasks = resp.get("tasks") or []
        if status == "rejected" or not tasks:
            err = str(resp.get("error") or resp.get("detail") or "Task rejected by Artemis")
            return GoalExecutionResult(
                succeeded=False,
                status="rejected",
                goal=goal,
                profile=profile,
                session_id=session_id,
                error=err,
                duration_sec=time.monotonic() - started,
                raw_session=resp,
            )

        admitted_sid = str(tasks[0].get("session_id") or session_id)
        if watcher and watcher.watch:
            watcher.start_sse_stream(admitted_sid)

        deadline = time.monotonic() + timeout
        terminal_states = {
            "completed",
            "success",
            "succeeded",
            "failed",
            "error",
            "cancelled",
            "stopped",
            "rejected",
        }
        while time.monotonic() < deadline:
            try:
                sess = self._http_json("GET", f"/api/sessions/{admitted_sid}", timeout=10.0)
            except urllib.error.HTTPError as exc:
                if exc.code == 404:
                    time.sleep(poll_interval)
                    continue
                raise
            except Exception:
                time.sleep(poll_interval)
                continue

            st = str(sess.get("status") or "").lower()
            if st in terminal_states:
                succeeded = st in ("completed", "success", "succeeded")
                output = (
                    sess.get("structured_output")
                    or sess.get("output")
                    or sess.get("final_output")
                    or sess.get("result")
                )
                explanation = (
                    sess.get("explanation")
                    or sess.get("summary")
                    or sess.get("final_report")
                )
                error = sess.get("error") if not succeeded else None
                steps = sess.get("steps") or sess.get("step_count") or 0
                steps_count = len(steps) if isinstance(steps, list) else int(steps or 0)
                return GoalExecutionResult(
                    succeeded=succeeded,
                    status=st,
                    goal=goal,
                    profile=profile,
                    session_id=admitted_sid,
                    output=output,
                    explanation=explanation,
                    error=error,
                    steps_count=steps_count,
                    duration_sec=time.monotonic() - started,
                    raw_session=sess,
                )
            time.sleep(poll_interval)

        # Timeout reached; stop task on daemon
        try:
            self._http_json("POST", "/api/stop", {"session_id": admitted_sid}, timeout=5.0)
        except Exception:
            pass
        return GoalExecutionResult(
            succeeded=False,
            status="timeout",
            goal=goal,
            profile=profile,
            session_id=admitted_sid,
            error=f"Task timed out after {timeout}s",
            duration_sec=time.monotonic() - started,
        )

    def _execute_via_cli_fallback(
        self,
        goal: str,
        *,
        session_id: str,
        profile: str,
        expected_output: str | None,
        locked_app_package: str | None,
        app_path: str | None,
        verification_level: str | None,
        explorer_mode: str | None,
        timeout: float,
        started: float,
    ) -> GoalExecutionResult:
        artemis_bin = shutil.which("artemis")
        cmd: list[str]
        if artemis_bin:
            cmd = [artemis_bin, "run", goal, "--profile", profile, "--standalone"]
        elif os.environ.get("ARTEMIS_SOURCE_DIR"):
            uv_bin = shutil.which("uv") or "uv"
            cmd = [
                uv_bin,
                "run",
                "--directory",
                os.environ["ARTEMIS_SOURCE_DIR"],
                "artemis",
                "run",
                goal,
                "--profile",
                profile,
                "--standalone",
            ]
        else:
            return GoalExecutionResult(
                succeeded=False,
                status="unavailable",
                goal=goal,
                profile=profile,
                session_id=session_id,
                error=(
                    f"Artemis Daemon is not reachable at {self.base_url} and no local 'artemis' CLI "
                    "was found. Start the stack with 'agentdroid up' or 'docker compose up -d'."
                ),
                duration_sec=time.monotonic() - started,
            )

        if self.device_serial:
            cmd.extend(["--device-serial", self.device_serial])
        if expected_output:
            cmd.extend(["--output-description", expected_output, "--enable-outputter"])
        if locked_app_package:
            cmd.extend(["--locked-app", locked_app_package])
        if app_path:
            cmd.extend(["--app-path", app_path])
        if verification_level:
            cmd.extend(["--verification-level", verification_level])
        if explorer_mode:
            cmd.extend(["--explorer-version", explorer_mode])
        cmd.extend(["--session-id", session_id])

        proc = subprocess.run(
            cmd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        succeeded = proc.returncode == 0
        stdout_tail = (proc.stdout or "").strip()[-2000:]
        stderr_tail = (proc.stderr or "").strip()[-2000:]
        return GoalExecutionResult(
            succeeded=succeeded,
            status="completed" if succeeded else "failed",
            goal=goal,
            profile=profile,
            session_id=session_id,
            output=stdout_tail if succeeded else None,
            explanation=stdout_tail if succeeded else None,
            error=stderr_tail or stdout_tail if not succeeded else None,
            duration_sec=time.monotonic() - started,
        )
