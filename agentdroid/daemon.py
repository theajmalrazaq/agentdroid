"""Persistent warm local Unix-socket daemon for zero-overhead AgentDroid CLI calls."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Any

from agentdroid.pipeline import CompoundPipeline, PipelineSpec

logger = logging.getLogger(__name__)

CACHE_DIR = Path.home() / ".cache" / "agentdroid"
DAEMON_SOCK_PATH = CACHE_DIR / "daemon.sock"
DAEMON_PID_PATH = CACHE_DIR / "daemon.pid"


def _send_daemon_request(payload: dict[str, Any], *, timeout: float = 120.0) -> dict[str, Any] | None:
    if not DAEMON_SOCK_PATH.exists():
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(str(DAEMON_SOCK_PATH))
            sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks: list[bytes] = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if not raw:
            return None
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def run_via_daemon(spec: PipelineSpec, *, timeout: float = 120.0) -> dict[str, Any] | None:
    """Execute a headless PipelineSpec through the warm background daemon if running."""
    return _send_daemon_request({"op": "run", "spec": dataclasses.asdict(spec)}, timeout=timeout)


def daemon_status() -> dict[str, Any]:
    """Return status of the persistent AgentDroid daemon."""
    res = _send_daemon_request({"op": "ping"}, timeout=1.5)
    if res and res.get("ok"):
        return {
            "running": True,
            "pid": res.get("pid"),
            "socket": str(DAEMON_SOCK_PATH),
        }
    return {"running": False, "pid": None, "socket": str(DAEMON_SOCK_PATH)}


def stop_daemon() -> dict[str, Any]:
    """Stop the persistent AgentDroid daemon if running."""
    res = _send_daemon_request({"op": "stop"}, timeout=2.0)
    if res and res.get("ok"):
        return {"stopped": True, "pid": res.get("pid")}
    if DAEMON_PID_PATH.exists():
        try:
            pid = int(DAEMON_PID_PATH.read_text(encoding="utf-8").strip())
            os.kill(pid, signal.SIGTERM)
            DAEMON_PID_PATH.unlink(missing_ok=True)
            DAEMON_SOCK_PATH.unlink(missing_ok=True)
            return {"stopped": True, "pid": pid}
        except (OSError, ValueError) as exc:
            logger.debug("Failed to stop daemon PID: %s", exc)
    DAEMON_SOCK_PATH.unlink(missing_ok=True)
    DAEMON_PID_PATH.unlink(missing_ok=True)
    return {"stopped": False, "pid": None}


def start_daemon(*, wait_sec: float = 5.0) -> dict[str, Any]:
    """Start the persistent warm daemon in the background if not already running."""
    st = daemon_status()
    if st["running"]:
        return {"started": False, "already_running": True, **st}

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DAEMON_SOCK_PATH.unlink(missing_ok=True)
    repo_root = str(Path(__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = f"{repo_root}:{env['PYTHONPATH']}" if env.get("PYTHONPATH") else repo_root
    subprocess.Popen(
        [sys.executable, "-m", "agentdroid.cli", "daemon", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=env,
    )
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        st = daemon_status()
        if st["running"]:
            return {"started": True, "already_running": False, **st}
        time.sleep(0.05)
    return {"started": False, "already_running": False, **daemon_status()}


def serve_daemon() -> int:
    """Run the warm Unix-socket daemon loop (keeps Python + Rust worker hot)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    DAEMON_SOCK_PATH.unlink(missing_ok=True)
    DAEMON_PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

    # Pre-warm Rust stdio worker if available
    try:
        from agentdroid import rust_bridge

        rust_bridge.get_worker()
    except (OSError, RuntimeError) as exc:
        logger.debug("Rust worker pre-warm skipped: %s", exc)

    running = True

    def _handle_sig(_signum: int, _frame: Any) -> None:
        nonlocal running
        running = False

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _handle_sig)
        signal.signal(signal.SIGINT, _handle_sig)

    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        srv.bind(str(DAEMON_SOCK_PATH))
        os.chmod(DAEMON_SOCK_PATH, 0o600)
        srv.listen(16)
        srv.settimeout(0.5)

        while running:
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            except OSError:
                break

            with conn:
                try:
                    chunks: list[bytes] = []
                    while True:
                        chunk = conn.recv(65536)
                        if not chunk:
                            break
                        chunks.append(chunk)
                        if b"\n" in chunk:
                            break
                    raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
                    req = json.loads(raw) if raw else {}
                    op = str(req.get("op") or "")
                    if op == "ping":
                        resp: dict[str, Any] = {"ok": True, "pid": os.getpid()}
                    elif op == "stop":
                        running = False
                        resp = {"ok": True, "pid": os.getpid()}
                    elif op == "run":
                        spec_dict = dict(req.get("spec") or {})
                        valid_keys = {f.name for f in dataclasses.fields(PipelineSpec)}
                        filtered = {k: v for k, v in spec_dict.items() if k in valid_keys}
                        spec = PipelineSpec(**filtered)
                        resp = CompoundPipeline(spec).run()
                    else:
                        resp = {"ok": False, "error": f"Unknown daemon op: {op}"}
                except Exception as exc:
                    resp = {"ok": False, "error": str(exc)}
                conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
    finally:
        try:
            srv.close()
        except OSError:
            pass
        DAEMON_SOCK_PATH.unlink(missing_ok=True)
        DAEMON_PID_PATH.unlink(missing_ok=True)
    return 0
