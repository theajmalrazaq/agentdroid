"""Direct client for the on-device Artemis Accessibility Helper (127.0.0.1:18888) with UIAutomator fallback.

Provides sub-second UI hierarchy dumps, semantic element targeting (by text, content-desc,
resource-id, or element index), scrolling, and gesture injection so the host AI agent
(Claude Code, Antigravity, Codex, Cursor, etc.) can drive Android directly with zero API keys.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from pathlib import Path
import re
import secrets
import socket
import tempfile
import threading
import time
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from agentdroid.adb import AdbDevice

logger = logging.getLogger(__name__)

HELPER_PACKAGE = "com.artemis.helper"
HELPER_SERVICE = f"{HELPER_PACKAGE}/.ArtemisAccessibilityService"
HELPER_RECEIVER = f"{HELPER_PACKAGE}/.TokenReceiver"
HELPER_ACTION = f"{HELPER_PACKAGE}.SET_TOKEN"
DEVICE_PORT = 18888

INPUT_DAEMON_PORT = 18889
INPUT_DAEMON_DEX_HOST = (
    Path(__file__).resolve().parent.parent
    / "packages"
    / "agentdroid-input-daemon"
    / "agentdroid-input.dex"
)
INPUT_DAEMON_DEX_DEVICE = "/data/local/tmp/agentdroid-input.dex"
INPUT_DAEMON_DEX_VENDOR = "/vendor/etc/artemis/agentdroid-input.dex"
INPUT_DAEMON_TOKEN_DEVICE = "/data/local/tmp/.agentdroid_input_token"
FAST_DUMP_PORT = 18890
FAST_DUMP_DEX_HOST = (
    Path(__file__).resolve().parent.parent
    / "packages"
    / "agentdroid-fast-dump"
    / "agentdroid-fast-dump.dex"
)
FAST_DUMP_DEX_DEVICE = "/data/local/tmp/agentdroid-fast-dump.dex"

_KEYCODE_MAP = {
    "BACK": "KEYCODE_BACK",
    "HOME": "KEYCODE_HOME",
    "RECENTS": "KEYCODE_APP_SWITCH",
    "ENTER": "KEYCODE_ENTER",
    "SEARCH": "KEYCODE_SEARCH",
    "DELETE": "KEYCODE_DEL",
    "TAB": "KEYCODE_TAB",
}


def _resolve_shared_token_path() -> Path:
    """Resolve the shared Artemis/AgentDroid helper session token path."""
    candidates = [
        Path(tempfile.gettempdir()) / "agentdroid" / "helper-token" / "session.token",
        Path.home() / ".cache" / "agentdroid" / "helper-token" / "session.token",
        Path(tempfile.gettempdir()) / "artemis" / "helper-token" / "session.token",
        Path.home() / ".cache" / "artemis" / "helper-token" / "session.token",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return candidates[0]


def get_or_create_helper_token() -> str:
    """Read or generate the 48-hex-char session token shared with Artemis."""
    env_tok = os.environ.get("AGENTDROID_HELPER_TOKEN")
    if env_tok and re.fullmatch(r"[0-9a-f]{32,128}", env_tok.strip()):
        return env_tok.strip()
    path = _resolve_shared_token_path()
    try:
        if path.is_file():
            text = path.read_text(encoding="utf-8").strip()
            if re.fullmatch(r"[0-9a-f]{32,128}", text):
                return text
    except OSError:
        pass
    token = secrets.token_hex(24)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(token)
    except OSError:
        pass
    return token


def _parse_swipe_args(params: dict[str, Any]) -> tuple[float, float, float, float, int]:
    """Normalize swipe coordinate and duration parameter aliases."""
    def _pick(*keys: str, default: float = 0.0) -> float:
        for k in keys:
            if params.get(k) is not None:
                return float(params[k])
        return default

    return (
        _pick("x1", "start_x", "startX"),
        _pick("y1", "start_y", "startY"),
        _pick("x2", "end_x", "endX"),
        _pick("y2", "end_y", "endY"),
        max(1, int(_pick("duration", "duration_ms", default=300))),
    )


def _is_ime_node(package_name: str, short_class: str) -> bool:
    if short_class == "Key":
        return True
    low = package_name.lower()
    return "inputmethod" in low or "latinime" in low or "gboard" in low


def select_ui_element(elements: list[dict[str, Any]], selector: str) -> dict[str, Any] | None:
    """Universal interactivity-scored element selector (#idx, btn:, edit:, exact:, id:, substring)."""
    sel = selector.strip()
    if not sel or not elements:
        return None

    try:
        from agentdroid import rust_bridge

        handled, el = rust_bridge.select_element(elements, sel)
        if handled:
            return el
    except (OSError, RuntimeError, ValueError) as exc:
        logger.debug("Rust select_element fallback: %s", exc)

    if sel.startswith("#") and sel[1:].isdigit():
        target_id = int(sel[1:])
        for el in elements:
            if el.get("id") == target_id:
                return el

    mode = "any"
    needle_raw = sel
    for prefix, m in (("btn:", "btn"), ("edit:", "edit"), ("exact:", "exact"), ("id:", "id"), ("text:", "text")):
        if sel.startswith(prefix):
            mode = m
            needle_raw = sel[len(prefix) :].strip()
            break

    needle = needle_raw.lower()
    if not needle:
        return None

    if mode in ("btn", "edit") and needle_raw.startswith("#") and needle_raw[1:].isdigit():
        nth = int(needle_raw[1:])
        if nth >= 1:
            cnt = 0
            for el in elements:
                cls_name = str(el.get("class") or "")
                is_kind = (
                    (mode == "btn" and (bool(el.get("clickable")) or "Button" in cls_name))
                    or (mode == "edit" and bool(el.get("editable")))
                )
                if is_kind:
                    cnt += 1
                    if cnt == nth:
                        return el
            return None

    best: tuple[int, int, dict[str, Any]] | None = None
    for pos, el in enumerate(elements):
        cls_name = str(el.get("class") or "")
        clickable = bool(el.get("clickable"))
        editable = bool(el.get("editable"))
        if mode == "btn" and not clickable and "Button" not in cls_name:
            continue
        if mode == "edit" and not editable:
            continue

        interactive_bonus = 20 if (clickable or editable) else 0
        non_webview_bonus = 0 if cls_name == "WebView" else 5
        sysui_penalty = -60 if el.get("systemui") else 0

        if mode == "id":
            fields = [(str(el.get("resource_id") or ""), 5)]
        elif mode == "text":
            fields = [
                (str(el.get("label") or ""), 4),
                (str(el.get("full_text") or ""), 4),
            ]
        else:
            fields = [
                (str(el.get("label") or ""), 4),
                (str(el.get("full_text") or ""), 4),
                (str(el.get("desc") or ""), 3),
                (str(el.get("resource_id") or ""), 5),
            ]

        field_score = 0
        for raw_val, weight in fields:
            v = raw_val.strip().lower()
            if not v:
                continue
            if v == needle:
                field_score = max(field_score, 100 + weight)
            elif mode != "exact" and needle in v:
                field_score = max(field_score, 40 + weight)

        if field_score == 0:
            continue

        total_score = field_score + interactive_bonus + non_webview_bonus + sysui_penalty
        if best is None or total_score > best[0]:
            best = (total_score, pos, el)

    if best is not None:
        return best[2]
    if sel.isdigit():
        target_id = int(sel)
        for el in elements:
            if el.get("id") == target_id:
                return el
    return None


class AccessibilityHelperClient:
    """Sub-second UI hierarchy, semantic locator, and gesture client backed by ArtemisAccessibilityHelper.apk and InputDaemon."""

    def __init__(self, adb: AdbDevice) -> None:
        self.adb = adb
        self._local_port: int | None = None
        self._input_local_port: int | None = None
        self._input_sock: socket.socket | None = None
        self._input_rfile: Any = None
        self._input_lock = threading.Lock()
        self._last_ping: dict[str, Any] | None = None
        self._last_sparse_fallback_at: float = 0.0
        self._display_size: tuple[int, int] | None = None
        self._token: str = get_or_create_helper_token()
        self._last_ui_blob: str | None = None

    def get_display_size(self) -> tuple[int, int]:
        if self._display_size is not None:
            return self._display_size
        if isinstance(self.adb, AdbDevice):
            try:
                size = self.adb.get_display_size()
                if isinstance(size, tuple) and len(size) == 2 and size[0] > 0 and size[1] > 0:
                    self._display_size = size
                    return size
            except (OSError, RuntimeError, ValueError) as exc:
                logger.debug("Display size query failed: %s", exc)
        return (1080, 2400)

    def close(self) -> None:
        """Close any cached persistent socket connections."""
        with self._input_lock:
            self._close_input_socket()

    def _close_input_socket(self) -> None:
        if self._input_rfile is not None:
            try:
                self._input_rfile.close()
            except OSError as exc:
                logger.debug("Closing input rfile failed: %s", exc)
            self._input_rfile = None
        if self._input_sock is not None:
            try:
                self._input_sock.close()
            except OSError as exc:
                logger.debug("Closing input socket failed: %s", exc)
            self._input_sock = None

    def _find_existing_forward(self, remote_port: int = DEVICE_PORT) -> int | None:
        if isinstance(self.adb, AdbDevice) and self.adb._use_rust_adb():
            try:
                from agentdroid import rust_bridge

                ok, pairs = rust_bridge.adb_forward_list(self.adb.serial)
                if ok:
                    for loc, rem in pairs:
                        if rem == remote_port:
                            return loc
            except (OSError, RuntimeError, ValueError) as exc:
                logger.debug("Rust adb_forward_list fallback: %s", exc)
        res = self.adb.run_adb(["forward", "--list"], timeout=5.0)
        for line in (res.stdout or "").splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == self.adb.serial:
                local, remote = parts[1], parts[2]
                if remote == f"tcp:{remote_port}" and local.startswith("tcp:"):
                    try:
                        return int(local[4:])
                    except ValueError:
                        continue
        return None

    def _ensure_forward(self, remote_port: int = DEVICE_PORT) -> int:
        if remote_port == DEVICE_PORT and self._local_port is not None:
            return self._local_port
        if remote_port == INPUT_DAEMON_PORT and self._input_local_port is not None:
            return self._input_local_port

        existing = self._find_existing_forward(remote_port=remote_port)
        if existing is not None:
            if remote_port == DEVICE_PORT:
                self._local_port = existing
            elif remote_port == INPUT_DAEMON_PORT:
                self._input_local_port = existing
            return existing

        if isinstance(self.adb, AdbDevice) and self.adb._use_rust_adb():
            try:
                from agentdroid import rust_bridge

                ok, local_port = rust_bridge.adb_forward_create(self.adb.serial, remote_port)
                if ok and local_port is not None:
                    if remote_port == DEVICE_PORT:
                        self._local_port = local_port
                    elif remote_port == INPUT_DAEMON_PORT:
                        self._input_local_port = local_port
                    return local_port
            except (OSError, RuntimeError, ValueError) as exc:
                logger.debug("Rust adb_forward_create fallback: %s", exc)

        res = self.adb.run_adb(["forward", "tcp:0", f"tcp:{remote_port}"], timeout=10.0)
        port_str = (res.stdout or "").strip()
        if res.returncode == 0 and port_str.isdigit():
            local_port = int(port_str)
            if remote_port == DEVICE_PORT:
                self._local_port = local_port
            elif remote_port == INPUT_DAEMON_PORT:
                self._input_local_port = local_port
            return local_port
        raise RuntimeError(
            f"Could not create adb forward to tcp:{remote_port} on {self.adb.serial}: {res.stderr}"
        )

    def _ensure_input_forward(self) -> int:
        return self._ensure_forward(remote_port=INPUT_DAEMON_PORT)

    def _send_input_cmd_locked(self, cmd_line: str, *, timeout: float = 3.0) -> str:
        if self._input_sock is None or self._input_rfile is None:
            port = self._ensure_input_forward()
            sock = socket.create_connection(("127.0.0.1", port), timeout=timeout)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            rfile = sock.makefile("r", encoding="utf-8", errors="replace")
            self._input_sock = sock
            self._input_rfile = rfile

        try:
            self._input_sock.settimeout(timeout)
            payload = f"{self._token}\t{cmd_line}\n".encode()
            self._input_sock.sendall(payload)
            line = self._input_rfile.readline()
            if not line:
                self._close_input_socket()
                raise ConnectionResetError("InputDaemon closed connection")
            return line.strip()
        except Exception:
            self._close_input_socket()
            raise

    def _input_daemon_ping(self) -> bool:
        try:
            with self._input_lock:
                resp = self._send_input_cmd_locked("ping", timeout=1.0)
            return resp == "OK pong"
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("InputDaemon ping failed: %s", exc)
            with self._input_lock:
                self._close_input_socket()
            return False

    def _launch_device_daemon(
        self,
        classpath: str,
        main_class: str,
        args: str,
        ping_fn: Any,
        *,
        kill_prefix: str = "",
        retries: int = 25,
    ) -> bool:
        """Spawn a detached app_process daemon via standard adb shell so it survives socket close."""
        inner = f"CLASSPATH={classpath} exec app_process / {main_class} {args}"
        launch_cmd = f'{kill_prefix}nohup sh -c "{inner}" </dev/null >/dev/null 2>&1 &'
        if hasattr(self.adb, "run_adb"):
            self.adb.run_adb(["shell", launch_cmd], timeout=5.0)
        else:
            self.adb.shell(launch_cmd, timeout=5.0)
        for _ in range(retries):
            if ping_fn():
                return True
            time.sleep(0.05)
        return False

    def _ensure_input_daemon(self, *, force: bool = False) -> bool:
        try:
            self._ensure_input_forward()
        except (OSError, RuntimeError) as exc:
            logger.debug("InputDaemon forward setup failed: %s", exc)
            return False

        if not force and self._input_daemon_ping():
            return True

        host_size = INPUT_DAEMON_DEX_HOST.stat().st_size if INPUT_DAEMON_DEX_HOST.is_file() else 0
        token_clean = re.sub(r"[^0-9A-Za-z._-]", "", self._token) or "agentdroid"
        check_cmd = (
            f"umask 077 && printf '%s\\n' '{token_clean}' > {INPUT_DAEMON_TOKEN_DEVICE} && "
            f"chmod 600 {INPUT_DAEMON_TOKEN_DEVICE}; "
            f"if [ -f {INPUT_DAEMON_DEX_VENDOR} ] && [ ! -s {INPUT_DAEMON_DEX_DEVICE} ]; then "
            f"cp -f {INPUT_DAEMON_DEX_VENDOR} {INPUT_DAEMON_DEX_DEVICE}; fi; "
            f"wc -c < {INPUT_DAEMON_DEX_DEVICE} 2>/dev/null || echo 0"
        )
        out = (self.adb.shell(check_cmd, timeout=6.0) or "").strip()
        last_line = out.splitlines()[-1].strip() if out else ""
        dev_size = int(last_line) if last_line.isdigit() else 0

        if host_size and dev_size != host_size:
            push_res = self.adb.run_adb(
                ["push", str(INPUT_DAEMON_DEX_HOST), INPUT_DAEMON_DEX_DEVICE], timeout=15.0
            )
            if push_res.returncode != 0 and dev_size == 0:
                return False
        elif dev_size == 0:
            return False

        with self._input_lock:
            self._close_input_socket()

        kill_prefix = (
            'for p in $(ps -A -o PID,NAME,ARGS | sed -n "s/^[[:space:]]*\\([0-9][0-9]*\\)[[:space:]]\\{1,\\}app_process[^[:space:]]*[[:space:]].*InputDaemon.*/\\1/p"); '
            'do [ "$p" != "$$" ] && kill "$p" 2>/dev/null || true; done; '
            if force
            else ""
        )
        return self._launch_device_daemon(
            INPUT_DAEMON_DEX_DEVICE,
            "com.agentdroid.InputDaemon",
            f"{INPUT_DAEMON_PORT} {INPUT_DAEMON_TOKEN_DEVICE}",
            self._input_daemon_ping,
            kill_prefix=kill_prefix,
        )

    def _input_daemon_exec(self, cmd_line: str, *, timeout: float = 3.0) -> str | None:
        try:
            self._ensure_input_forward()
        except (OSError, RuntimeError) as exc:
            logger.debug("InputDaemon forward unavailable: %s", exc)
            return None

        for attempt in range(2):
            try:
                with self._input_lock:
                    resp = self._send_input_cmd_locked(cmd_line, timeout=timeout)
                if resp.startswith("OK"):
                    return resp
                if resp.startswith("ERR auth") and attempt == 0:
                    if self._ensure_input_daemon(force=True):
                        continue
                return None
            except TimeoutError:
                with self._input_lock:
                    self._close_input_socket()
                return None
            except (OSError, RuntimeError) as exc:
                logger.debug("InputDaemon command failed (attempt %d): %s", attempt + 1, exc)
                with self._input_lock:
                    self._close_input_socket()
                if attempt == 0:
                    self._input_local_port = None
                    if self._input_daemon_ping():
                        continue
                    if self._ensure_input_daemon(force=True):
                        continue
                return None
        return None

    def _input_daemon_action(self, cmd: str, **params: Any) -> dict[str, Any] | None:
        c = cmd.strip().lower()
        if c == "tap":
            x, y = float(params["x"]), float(params["y"])
            resp = self._input_daemon_exec(f"tap\t{x:.2f}\t{y:.2f}", timeout=3.0)
            if resp:
                return {"success": True, "backend": "input_daemon", "center": [round(x), round(y)]}
            return None
        if c == "long_press":
            x, y = float(params["x"]), float(params["y"])
            dur = max(1, int(params.get("duration", 1000)))
            resp = self._input_daemon_exec(
                f"long_press\t{x:.2f}\t{y:.2f}\t{dur}",
                timeout=max(3.0, dur / 1000.0 + 2.0),
            )
            if resp:
                return {"success": True, "backend": "input_daemon", "center": [round(x), round(y)]}
            return None
        if c == "swipe":
            x1, y1, x2, y2, dur = _parse_swipe_args(params)
            resp = self._input_daemon_exec(
                f"swipe\t{x1:.2f}\t{y1:.2f}\t{x2:.2f}\t{y2:.2f}\t{dur}",
                timeout=max(3.0, dur / 1000.0 + 2.0),
            )
            if resp:
                return {"success": True, "backend": "input_daemon"}
            return None
        if c == "global":
            act = re.sub(r"\s+", "", str(params.get("action", "")).upper())
            if not act:
                return None
            keycode = _KEYCODE_MAP.get(act, act if act.startswith("KEYCODE_") else f"KEYCODE_{act}")
            resp = self._input_daemon_exec(f"key\t{keycode}", timeout=3.0)
            if resp:
                return {"success": True, "backend": "input_daemon", "keycode": keycode}
            return None
        if c == "type":
            text_str = str(params.get("text", ""))
            if params.get("append"):
                self._input_daemon_exec("key\tKEYCODE_MOVE_END", timeout=1.5)
            if text_str.isascii():
                b64 = base64.b64encode(text_str.encode("utf-8")).decode("ascii")
                resp = self._input_daemon_exec(
                    f"text_b64\t{b64}",
                    timeout=max(5.0, len(text_str) * 0.1 + 3.0),
                )
                if resp:
                    return {"success": True, "backend": "input_daemon"}
            elif hasattr(self.adb, "set_clipboard"):
                try:
                    if self.adb.set_clipboard(text_str):
                        resp = self._input_daemon_exec("key\tKEYCODE_PASTE", timeout=2.0)
                        if resp:
                            return {"success": True, "backend": "input_daemon_paste"}
                except (OSError, RuntimeError) as exc:
                    logger.debug("InputDaemon clipboard paste fallback failed: %s", exc)
            return None
        return None

    def push_token(self) -> bool:
        res = self.adb.run_adb(
            [
                "shell",
                "am",
                "broadcast",
                "-n",
                HELPER_RECEIVER,
                "-a",
                HELPER_ACTION,
                "--es",
                "token",
                self._token,
            ],
            timeout=10.0,
        )
        out = f"{res.stdout or ''}\n{res.stderr or ''}"
        return res.returncode == 0 and "Broadcast completed" in out

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        timeout: float = 5.0,
        retry_auth: bool = True,
    ) -> dict[str, Any]:
        port = self._ensure_forward()
        url = f"http://127.0.0.1:{port}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {
            "X-Artemis-Token": self._token,
            "Accept": "application/json",
        }
        if data is not None:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code == 401 and retry_auth:
                self.push_token()
                return self._request(method, path, body, timeout=timeout, retry_auth=False)
            raise

    def ping(self) -> dict[str, Any] | None:
        try:
            res = self._request("GET", "/ping", timeout=2.5)
            if isinstance(res, dict) and res.get("success"):
                if not res.get("authenticated"):
                    self.push_token()
                    res = self._request("GET", "/ping", timeout=2.5, retry_auth=False)
                self._last_ping = res
                return res
        except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
            logger.debug("Helper /ping failed: %s", exc)
            self._local_port = None
        self._last_ping = None
        return None

    def ensure_ready(self) -> bool:
        """Ensure the helper APK is installed, service is bound, and HTTP server answers."""
        if self.ping() is not None:
            self._ensure_fast_dump()
            return True
        # ping() clears a stale cached forward port on error; retry once before provisioning
        if self.ping() is not None:
            self._ensure_fast_dump()
            return True
        prov = self.adb.provision_silent(force=False, quiet=True)
        self._local_port = None
        self._input_local_port = None
        with self._input_lock:
            self._close_input_socket()
        for _ in range(5):
            if self.ping() is not None:
                self._ensure_fast_dump()
                return True
            time.sleep(0.4)
        if isinstance(prov, dict) and prov.get("action") == "already_provisioned":
            self.adb.provision_silent(force=True, quiet=True)
            self._local_port = None
            for _ in range(3):
                if self.ping() is not None:
                    self._ensure_fast_dump()
                    return True
                time.sleep(0.4)
        self._ensure_fast_dump()
        return False

    def action(self, cmd: str, **params: Any) -> dict[str, Any]:
        """Execute a low-latency action via InputDaemon (touch/gesture) or Accessibility Helper (/action)."""
        c = cmd.strip().lower()
        if c in ("tap", "long_press", "swipe"):
            res = self._input_daemon_action(c, **params)
            if res is not None:
                return res

        if self.ensure_ready():
            payload = {"cmd": cmd, **params}
            try:
                res = self._request("POST", "/action", payload, timeout=5.0)
                if res.get("success"):
                    res.setdefault("backend", "helper_ipc")
                    return res
            except (OSError, urllib.error.URLError, RuntimeError, ValueError) as exc:
                logger.debug("Helper /action failed for %s: %s", cmd, exc)

        if c in ("global", "type"):
            res = self._input_daemon_action(c, **params)
            if res is not None:
                return res

        return self._fallback_adb_action(cmd, **params)

    def _fallback_adb_action(self, cmd: str, **params: Any) -> dict[str, Any]:
        c = cmd.lower()
        if c == "tap":
            x, y = int(params["x"]), int(params["y"])
            self.adb.shell(f"input tap {x} {y}")
            return {"success": True, "backend": "adb_input", "center": [x, y]}
        if c == "long_press":
            x, y = int(params["x"]), int(params["y"])
            dur = int(params.get("duration", 1000))
            self.adb.shell(f"input swipe {x} {y} {x} {y} {dur}")
            return {"success": True, "backend": "adb_input", "center": [x, y]}
        if c == "swipe":
            sx1, sy1, sx2, sy2, dur = _parse_swipe_args(params)
            self.adb.shell(f"input swipe {int(sx1)} {int(sy1)} {int(sx2)} {int(sy2)} {dur}")
            return {"success": True, "backend": "adb_input"}
        if c == "type":
            if params.get("append"):
                self._input_daemon_action("global", action="MOVE_END")
            text = str(params.get("text", ""))
            if hasattr(self.adb, "set_clipboard"):
                try:
                    if self.adb.set_clipboard(text):
                        self.adb.shell("input keyevent KEYCODE_PASTE")
                        return {"success": True, "backend": "adb_clipboard_paste"}
                except (OSError, RuntimeError) as exc:
                    logger.debug("ADB clipboard paste fallback failed: %s", exc)
            escaped = text.replace(" ", "%s").replace("'", "")
            self.adb.shell(f"input text '{escaped}'")
            return {"success": True, "backend": "adb_input"}
        if c == "global":
            act = str(params.get("action", "")).upper()
            keycode = _KEYCODE_MAP.get(act, act if act.startswith("KEYCODE_") else f"KEYCODE_{act}")
            self.adb.shell(f"input keyevent {keycode}")
            return {"success": True, "backend": "adb_input"}
        return {"success": False, "error": f"Unsupported fallback action: {cmd}"}

    def find_element(
        self,
        selector: str,
        *,
        max_elements: int = 120,
        include_ime: bool = False,
    ) -> dict[str, Any] | None:
        """Locate a UI element using interactivity-scored matching (#idx, btn:, edit:, exact:, id:, substring)."""
        sel = selector.strip()
        if not sel:
            return None
        ui = self.dump_compact_ui(max_elements=max_elements, include_ime=include_ime)
        elements = ui.get("elements") or []
        return select_ui_element(elements, sel)

    def tap_element(self, selector: str, *, timeout: float = 8.0) -> dict[str, Any]:
        """Wait up to timeout for an element matching selector (text, id, #index) and tap its center."""
        deadline = time.monotonic() + max(0.5, timeout)
        while True:
            el = self.find_element(selector)
            if el is not None:
                cx, cy = el["center"]
                res = self.action("tap", x=float(cx), y=float(cy))
                return {
                    "success": bool(res.get("success", True)),
                    "selector": selector,
                    "matched_element": el,
                    "center": [cx, cy],
                }
            if time.monotonic() >= deadline:
                break
            time.sleep(0.15)
        return {
            "success": False,
            "selector": selector,
            "error": f"Element matching {selector!r} not found on screen",
        }

    def fill_element(self, selector: str, text: str, *, submit: bool = False) -> dict[str, Any]:
        """Tap an input field matching selector, enter text, and optionally press ENTER."""
        tap_res = self.tap_element(selector, timeout=6.0)
        if not tap_res.get("success"):
            return tap_res
        time.sleep(0.05)
        type_res = self.action("type", text=text, append=False)
        if submit:
            time.sleep(0.05)
            self.action("global", action="ENTER")
        return {
            "success": bool(type_res.get("success", True)),
            "selector": selector,
            "text": text,
            "matched_element": tap_res.get("matched_element"),
        }

    def scroll(self, direction: str = "down") -> dict[str, Any]:
        """Perform a resolution-scaled directional scroll gesture on the screen."""
        w, h = self.get_display_size()
        cx, cy = w // 2, h // 2
        y_top, y_bot = int(h * 0.20), int(h * 0.65)
        x_left, x_right = int(w * 0.16), int(w * 0.84)
        d = direction.strip().lower()
        if d == "down":
            return self.action("swipe", x1=cx, y1=y_bot, x2=cx, y2=y_top, duration=300)
        if d == "up":
            return self.action("swipe", x1=cx, y1=y_top, x2=cx, y2=y_bot, duration=300)
        if d == "left":
            return self.action("swipe", x1=x_right, y1=cy, x2=x_left, y2=cy, duration=280)
        if d == "right":
            return self.action("swipe", x1=x_left, y1=cy, x2=x_right, y2=cy, duration=280)
        return {"success": False, "error": f"Unknown scroll direction: {direction!r}"}

    def scroll_to_text(self, text_needle: str, *, max_scrolls: int = 8, direction: str = "down") -> dict[str, Any]:
        """Scroll until an element matching text_needle becomes visible on screen."""
        for attempt in range(max_scrolls + 1):
            el = self.find_element(text_needle)
            if el is not None:
                return {"success": True, "found": True, "scrolls": attempt, "element": el}
            if attempt < max_scrolls:
                self.scroll(direction)
                time.sleep(0.15)
        return {
            "success": False,
            "found": False,
            "scrolls": max_scrolls,
            "error": f"Text {text_needle!r} not found after {max_scrolls} scrolls",
        }

    def _ensure_fast_dump(self) -> int | None:
        if not isinstance(self.adb, AdbDevice):
            return None
        try:
            port = self._ensure_forward(remote_port=FAST_DUMP_PORT)
        except (OSError, RuntimeError) as exc:
            logger.debug("FastDump forward setup failed: %s", exc)
            return None

        def _ping_fast(p: int) -> bool:
            try:
                with socket.create_connection(("127.0.0.1", p), timeout=0.6) as s:
                    s.settimeout(0.8)
                    s.sendall(f"{self._token}\tping\n".encode())
                    return s.recv(64).startswith(b"OK pong")
            except OSError:
                return False

        if _ping_fast(port):
            return port
        if not FAST_DUMP_DEX_HOST.is_file():
            return None
        host_size = FAST_DUMP_DEX_HOST.stat().st_size
        token_clean = re.sub(r"[^0-9A-Za-z._-]", "", self._token) or "agentdroid"
        check_cmd = (
            f"umask 077 && printf '%s\\n' '{token_clean}' > {INPUT_DAEMON_TOKEN_DEVICE} && "
            f"chmod 600 {INPUT_DAEMON_TOKEN_DEVICE}; "
            f"wc -c < {FAST_DUMP_DEX_DEVICE} 2>/dev/null || echo 0"
        )
        out = (self.adb.shell(check_cmd, timeout=5.0) or "").strip()
        last_line = out.splitlines()[-1].strip() if out else ""
        dev_size = int(last_line) if last_line.isdigit() else 0
        if dev_size != host_size:
            push_res = self.adb.run_adb(["push", str(FAST_DUMP_DEX_HOST), FAST_DUMP_DEX_DEVICE], timeout=10.0)
            if push_res.returncode != 0:
                return None
        launched = self._launch_device_daemon(
            f"/system/framework/uiautomator.jar:{FAST_DUMP_DEX_DEVICE}",
            "com.agentdroid.FastDump",
            f"{FAST_DUMP_PORT} {INPUT_DAEMON_TOKEN_DEVICE}",
            lambda: _ping_fast(port),
        )
        return port if launched else None

    def _fast_dump_xml(self) -> str:
        port = self._ensure_fast_dump()
        if port is None:
            return ""
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1.5) as s:
                s.settimeout(2.5)
                s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                s.sendall(f"{self._token}\tdump\n".encode())
                f = s.makefile("rb")
                hdr = f.readline().decode("utf-8", errors="replace").strip()
                if not hdr.startswith("OK "):
                    return ""
                byte_len = int(hdr.split()[1])
                if byte_len <= 0 or byte_len > 8 * 1024 * 1024:
                    return ""
                data = f.read(byte_len).decode("utf-8", errors="replace")
                return data if ("<hierarchy" in data or "<displays" in data) else ""
        except (OSError, ValueError) as exc:
            logger.debug("FastDump XML fetch failed: %s", exc)
            return ""

    def _dump_uiautomator_xml(self) -> str:
        if isinstance(self.adb, AdbDevice):
            fast = self._fast_dump_xml()
            if fast:
                return fast
        self.adb.shell("timeout 4 uiautomator dump /sdcard/agentdroid_ui.xml >/dev/null 2>&1 || true")
        return self.adb.shell("cat /sdcard/agentdroid_ui.xml 2>/dev/null || true")

    @staticmethod
    def _parse_hierarchy_xml(
        xml_str: str,
        max_elements: int,
        *,
        include_ime: bool = False,
    ) -> tuple[list[dict[str, Any]], int, bool, tuple[int, int], str | None]:
        """Parse UI XML via Rust fast-path (or Python fallback) returning (elements, app_count, has_systemui, display_size, error)."""
        if not xml_str or "<" not in xml_str:
            return [], 0, False, (1080, 2400), None

        try:
            from agentdroid import rust_bridge

            r = rust_bridge.parse_xml(xml_str, max_elements=max_elements, include_ime=include_ime)
            if r is not None:
                if not r.get("ok"):
                    return [], 0, False, (1080, 2400), str(r.get("error") or "XML parse error")
                ds = r.get("display_size") or [1080, 2400]
                disp = (int(ds[0]), int(ds[1])) if len(ds) == 2 else (1080, 2400)
                return (
                    list(r.get("elements") or []),
                    int(r.get("non_sysui_count") or 0),
                    bool(r.get("has_systemui")),
                    disp,
                    None,
                )
        except (OSError, RuntimeError, ValueError) as exc:
            logger.debug("Rust parse_xml fallback: %s", exc)

        elements: list[dict[str, Any]] = []
        non_sysui_count = 0
        has_systemui = False
        max_w, max_h = 0, 0
        try:
            xml_clean = xml_str[xml_str.find("<") :]
            root = ET.fromstring(xml_clean)
            idx = 1
            for node in root.iter():
                node_pkg = (node.attrib.get("package") or "").strip()
                if node_pkg == "com.android.systemui":
                    has_systemui = True

                bounds_str = node.attrib.get("bounds") or ""
                m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
                if m:
                    x1, y1, x2, y2 = map(int, m.groups())
                    if x2 > max_w:
                        max_w = x2
                    if y2 > max_h:
                        max_h = y2
                else:
                    continue

                if x2 <= x1 or y2 <= y1:
                    continue

                class_raw = node.attrib.get("class") or ""
                short_cls = class_raw.rsplit(".", 1)[-1]
                if not include_ime and _is_ime_node(node_pkg, short_cls):
                    continue

                text = (node.attrib.get("text") or "").strip()
                desc = (node.attrib.get("content-desc") or "").strip()
                res_id = (node.attrib.get("resource-id") or "").strip()
                clickable = node.attrib.get("clickable") == "true"
                editable = "EditText" in class_raw

                if not (text or desc or clickable or editable):
                    continue
                if len(elements) >= max_elements:
                    continue

                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                short_id = res_id.split("/")[-1] if "/" in res_id else res_id
                raw_label = text or desc or short_id or short_cls
                label = raw_label[:180]
                item: dict[str, Any] = {
                    "id": idx,
                    "label": label,
                    "class": short_cls,
                    "center": [cx, cy],
                }
                if (editable or len(raw_label) > 180) and raw_label != label:
                    item["full_text"] = raw_label
                if text and desc and text != desc:
                    item["desc"] = desc[:120]
                if short_id and short_id != label:
                    item["resource_id"] = short_id
                if clickable:
                    item["clickable"] = True
                if editable:
                    item["editable"] = True
                if node_pkg == "com.android.systemui":
                    item["systemui"] = True
                elements.append(item)
                if node_pkg != "com.android.systemui":
                    non_sysui_count += 1
                idx += 1
        except ET.ParseError as exc:
            return [], 0, has_systemui, (1080, 2400), str(exc)

        disp = (max_w, max_h) if max_w > 0 and max_h > 0 else (1080, 2400)
        return elements, non_sysui_count, has_systemui, disp, None

    def dump_compact_ui(
        self,
        *,
        max_elements: int = 80,
        allow_sparse_fallback: bool = True,
        include_ime: bool = False,
    ) -> dict[str, Any]:
        """Return compact numbered UI elements for minimal AI agent token consumption."""
        xml_str = ""
        backend = "helper"
        fg: dict[str, str | None] | None = None

        self._last_ping = None
        if self.ensure_ready():
            ping_res = self._last_ping
            if isinstance(ping_res, dict):
                pkg = ping_res.get("package")
                act = ping_res.get("activity")
                if pkg and str(pkg).lower() != "null":
                    pkg_str = str(pkg)
                    act_str = str(act) if act and str(act).lower() != "null" else None
                    is_overlay = (
                        "inputmethod" in pkg_str.lower()
                        or pkg_str == "com.android.systemui"
                        or act_str in ("android.view.View", "android.inputmethodservice.SoftInputWindow")
                    )
                    if not is_overlay:
                        fg = {
                            "package": pkg_str,
                            "activity": act_str,
                            "component": f"{pkg_str}/{act_str}" if act_str else None,
                        }
            try:
                port = self._ensure_forward()
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/hierarchy.xml",
                    headers={"X-Artemis-Token": self._token},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    xml_str = resp.read().decode("utf-8", errors="replace")
            except (OSError, urllib.error.URLError, RuntimeError) as exc:
                logger.debug("Helper /hierarchy.xml request failed: %s", exc)
                xml_str = ""

        if fg is None:
            fg = self.adb.foreground_app()

        if not xml_str or ("<hierarchy" not in xml_str and "<displays" not in xml_str):
            if not allow_sparse_fallback:
                return {
                    "backend": "helper",
                    "foreground": fg,
                    "display_size": list(self.get_display_size()),
                    "element_count": 0,
                    "elements": [],
                }
            backend = "uiautomator"
            xml_str = self._dump_uiautomator_xml()

        elements, non_sysui_count, has_systemui, disp_size, parse_error = self._parse_hierarchy_xml(
            xml_str, max_elements, include_ime=include_ime
        )
        self._display_size = disp_size
        if isinstance(self.adb, AdbDevice):
            self.adb.set_display_size_hint(disp_size[0], disp_size[1])

        if parse_error is not None:
            return {
                "backend": backend,
                "foreground": fg,
                "display_size": list(disp_size),
                "element_count": 0,
                "elements": [],
                "parse_error": parse_error,
            }

        # Recover rich WebView/multi-window nodes when helper only sees system bar + sparse stub,
        # OR when a WebView is present on screen and helper may lack descendant child text.
        has_webview = any(el.get("class") == "WebView" for el in elements)
        need_rich_dump = (has_systemui and non_sysui_count <= 2) or has_webview
        if (allow_sparse_fallback or has_webview) and backend == "helper" and need_rich_dump:
            fast_xml = self._fast_dump_xml()
            if fast_xml:
                fast_els, fast_non_sysui, _, fast_disp, fast_err = self._parse_hierarchy_xml(
                    fast_xml, max_elements, include_ime=include_ime
                )
                if fast_err is None and (
                    fast_non_sysui > non_sysui_count
                    or (has_webview and len(fast_els) >= len(elements))
                ):
                    backend = "fast_dump"
                    elements = fast_els
                    self._display_size = fast_disp
            elif allow_sparse_fallback and (
                (has_webview and (time.monotonic() - self._last_sparse_fallback_at) >= 0.1)
                or (
                    (time.monotonic() - self._last_sparse_fallback_at) >= 1.5
                    and non_sysui_count <= 2
                )
            ):
                self._last_sparse_fallback_at = time.monotonic()
                uia_xml = self._dump_uiautomator_xml()
                uia_els, uia_non_sysui, _, uia_disp, uia_err = self._parse_hierarchy_xml(
                    uia_xml, max_elements, include_ime=include_ime
                )
                if uia_err is None and (
                    uia_non_sysui > non_sysui_count
                    or (has_webview and len(uia_els) >= len(elements))
                ):
                    backend = "uiautomator"
                    elements = uia_els
                    self._display_size = uia_disp

        parts: list[str] = []
        for el in elements:
            for k in ("full_text", "label", "desc", "resource_id"):
                v = el.get(k)
                if v:
                    parts.append(str(v).strip().lower())
        self._last_ui_blob = "\n".join(parts)

        return {
            "backend": backend,
            "foreground": fg,
            "display_size": list(self.get_display_size()),
            "element_count": len(elements),
            "elements": elements,
        }
