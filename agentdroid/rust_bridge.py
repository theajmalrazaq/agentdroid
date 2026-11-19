"""Thread-safe persistent bridge to the native Rust `agentdroid-fast` engine."""

from __future__ import annotations

import atexit
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import threading
from typing import Any

logger = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUST_BIN = REPO_ROOT / "rust" / "target" / "release" / "agentdroid-fast"


def find_rust_binary() -> str | None:
    """Locate the compiled `agentdroid-fast` binary unless disabled via `AGENTDROID_NO_RUST=1`."""
    if os.environ.get("AGENTDROID_NO_RUST") == "1":
        return None
    env_bin = os.environ.get("AGENTDROID_FAST_BIN")
    if env_bin and Path(env_bin).is_file():
        return env_bin
    if DEFAULT_RUST_BIN.is_file():
        return str(DEFAULT_RUST_BIN)
    return shutil.which("agentdroid-fast")


class RustWorker:
    """Persistent `agentdroid-fast serve` stdio JSON-line subprocess worker."""

    def __init__(self, bin_path: str | None = None) -> None:
        self._bin_path = bin_path or find_rust_binary()
        self._proc: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()

    def _ensure_started(self) -> subprocess.Popen[str] | None:
        if not self._bin_path:
            return None
        if self._proc is not None and self._proc.poll() is None:
            return self._proc
        try:
            self._proc = subprocess.Popen(
                [self._bin_path, "serve"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            return self._proc
        except OSError:
            self._proc = None
            return None

    def close(self) -> None:
        with self._lock:
            self._close_locked()

    def _close_locked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=1.0)
        except (OSError, subprocess.SubprocessError):
            try:
                proc.kill()
            except OSError as exc:
                logger.debug("Failed killing Rust worker: %s", exc)

    def call(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if os.environ.get("AGENTDROID_NO_RUST") == "1":
            return None
        if not self._bin_path:
            self._bin_path = find_rust_binary()
        if not self._bin_path:
            return None

        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            for attempt in range(2):
                proc = self._ensure_started()
                if proc is None or proc.stdin is None or proc.stdout is None:
                    return None
                try:
                    proc.stdin.write(line)
                    proc.stdin.flush()
                    resp_line = proc.stdout.readline()
                    if not resp_line:
                        self._close_locked()
                        if attempt == 0:
                            continue
                        return None
                    parsed = json.loads(resp_line)
                    return parsed if isinstance(parsed, dict) else None
                except (OSError, ValueError, json.JSONDecodeError) as exc:
                    logger.debug("Rust worker call attempt %d failed: %s", attempt + 1, exc)
                    self._close_locked()
                    if attempt == 0:
                        continue
                    return None
        return None


_DEFAULT_WORKER = RustWorker()
atexit.register(_DEFAULT_WORKER.close)


def get_worker() -> RustWorker:
    return _DEFAULT_WORKER


def shutdown_worker() -> None:
    _DEFAULT_WORKER.close()


def adb_devices() -> tuple[bool, str]:
    resp = _DEFAULT_WORKER.call({"op": "adb_devices"})
    if resp and resp.get("ok"):
        return True, str(resp.get("output") or "")
    return False, ""


def adb_state(serial: str) -> tuple[bool, str]:
    resp = _DEFAULT_WORKER.call({"op": "adb_state", "serial": serial})
    if resp is not None:
        if resp.get("ok"):
            return True, str(resp.get("state") or "")
        return True, ""
    return False, ""


def adb_shell(serial: str, cmd: str, *, timeout_ms: int = 30000) -> tuple[bool, str]:
    resp = _DEFAULT_WORKER.call(
        {"op": "adb_shell", "serial": serial, "cmd": cmd, "timeout_ms": int(timeout_ms)}
    )
    if resp and resp.get("ok"):
        return True, str(resp.get("output") or "")
    return False, ""


def adb_forward_list(serial: str) -> tuple[bool, list[tuple[int, int]]]:
    resp = _DEFAULT_WORKER.call({"op": "adb_forward_list", "serial": serial})
    if resp and resp.get("ok"):
        pairs = [
            (int(item["local"]), int(item["remote"]))
            for item in (resp.get("forwards") or [])
            if "local" in item and "remote" in item
        ]
        return True, pairs
    return False, []


def adb_forward_create(serial: str, remote_port: int) -> tuple[bool, int | None]:
    resp = _DEFAULT_WORKER.call(
        {"op": "adb_forward_create", "serial": serial, "remote": int(remote_port)}
    )
    if resp and resp.get("ok") and resp.get("port") is not None:
        return True, int(resp["port"])
    return False, None


def parse_xml(
    xml: str,
    *,
    max_elements: int = 80,
    include_ime: bool = False,
) -> dict[str, Any] | None:
    resp = _DEFAULT_WORKER.call(
        {
            "op": "parse_xml",
            "xml": xml,
            "max_elements": int(max_elements),
            "include_ime": bool(include_ime),
        }
    )
    return resp


def select_element(
    elements: list[dict[str, Any]],
    selector: str,
) -> tuple[bool, dict[str, Any] | None]:
    resp = _DEFAULT_WORKER.call(
        {"op": "select", "elements": elements, "selector": selector}
    )
    if resp and resp.get("ok"):
        el = resp.get("element")
        return True, (el if isinstance(el, dict) else None)
    return False, None


def ping_helper(
    serial: str,
    token: str,
    *,
    timeout_ms: int = 1500,
) -> tuple[bool, dict[str, Any] | None]:
    resp = _DEFAULT_WORKER.call(
        {
            "op": "ping_helper",
            "serial": serial,
            "token": token,
            "timeout_ms": int(timeout_ms),
        }
    )
    if resp is None:
        return False, None
    if resp.get("ok") and isinstance(resp.get("ping"), dict):
        return True, resp["ping"]
    return True, None


def dump_ui(
    serial: str,
    token: str,
    *,
    max_elements: int = 80,
    include_ime: bool = False,
    allow_sparse_fallback: bool = True,
) -> dict[str, Any] | None:
    resp = _DEFAULT_WORKER.call(
        {
            "op": "dump_ui",
            "serial": serial,
            "token": token,
            "max_elements": int(max_elements),
            "include_ime": bool(include_ime),
            "allow_sparse_fallback": bool(allow_sparse_fallback),
        }
    )
    if resp and resp.get("ok") and isinstance(resp.get("ui"), dict):
        return resp["ui"]
    return None


def wait_condition(
    serial: str,
    token: str,
    *,
    mode: str,
    patterns: list[str],
    timeout_sec: float = 25.0,
    include_ime: bool = False,
) -> dict[str, Any] | None:
    resp = _DEFAULT_WORKER.call(
        {
            "op": "wait",
            "serial": serial,
            "token": token,
            "mode": mode,
            "patterns": patterns,
            "timeout_sec": float(timeout_sec),
            "include_ime": bool(include_ime),
        }
    )
    if resp and resp.get("ok") and isinstance(resp.get("result"), dict):
        return resp["result"]
    return None


def input_cmd(
    serial: str,
    token: str,
    cmd_line: str,
    *,
    timeout_ms: int = 3000,
) -> tuple[bool, str | None]:
    resp = _DEFAULT_WORKER.call(
        {
            "op": "input_cmd",
            "serial": serial,
            "token": token,
            "cmd_line": cmd_line,
            "timeout_ms": int(timeout_ms),
        }
    )
    if resp is None:
        return False, None
    if resp.get("ok"):
        return True, str(resp.get("resp") or "OK")
    return False, str(resp.get("error") or "")
