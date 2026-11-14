"""Direct client for the on-device Artemis Accessibility Helper (127.0.0.1:18888) with UIAutomator fallback."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from typing import Any
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from agentdroid.adb import AdbDevice

HELPER_PACKAGE = "com.artemis.helper"
HELPER_SERVICE = f"{HELPER_PACKAGE}/.ArtemisAccessibilityService"
HELPER_RECEIVER = f"{HELPER_PACKAGE}/.TokenReceiver"
HELPER_ACTION = f"{HELPER_PACKAGE}.SET_TOKEN"
DEVICE_PORT = 18888


def _resolve_shared_token_path() -> Path:
    """Resolve the shared Artemis/AgentDroid helper session token path."""
    candidates = [
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


class AccessibilityHelperClient:
    """Sub-second UI hierarchy and gesture client backed by ArtemisAccessibilityHelper.apk."""

    def __init__(self, adb: AdbDevice) -> None:
        self.adb = adb
        self._local_port: int | None = None
        self._token: str = get_or_create_helper_token()

    def _find_existing_forward(self) -> int | None:
        res = self.adb.run_adb(["forward", "--list"], timeout=5.0)
        for line in (res.stdout or "").splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == self.adb.serial:
                local, remote = parts[1], parts[2]
                if remote == f"tcp:{DEVICE_PORT}" and local.startswith("tcp:"):
                    try:
                        return int(local[4:])
                    except ValueError:
                        continue
        return None

    def _ensure_forward(self) -> int:
        if self._local_port is not None:
            return self._local_port
        existing = self._find_existing_forward()
        if existing is not None:
            self._local_port = existing
            return existing
        res = self.adb.run_adb(["forward", "tcp:0", f"tcp:{DEVICE_PORT}"], timeout=10.0)
        port_str = (res.stdout or "").strip()
        if res.returncode == 0 and port_str.isdigit():
            self._local_port = int(port_str)
            return self._local_port
        raise RuntimeError(
            f"Could not create adb forward to {HELPER_PACKAGE} on {self.adb.serial}: {res.stderr}"
        )

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
                return res
        except Exception:
            pass
        return None

    def ensure_ready(self) -> bool:
        """Ensure the helper APK is installed, service is bound, and HTTP server answers."""
        if self.ping() is not None:
            return True
        self.adb.provision_silent(force=False, quiet=True)
        self._local_port = None
        for _ in range(5):
            if self.ping() is not None:
                return True
            time.sleep(0.4)
        return False

    def action(self, cmd: str, **params: Any) -> dict[str, Any]:
        """Execute a low-latency action via the Accessibility Helper (/action)."""
        if not self.ensure_ready():
            return self._fallback_adb_action(cmd, **params)
        payload = {"cmd": cmd, **params}
        try:
            return self._request("POST", "/action", payload, timeout=5.0)
        except Exception:
            return self._fallback_adb_action(cmd, **params)

    def _fallback_adb_action(self, cmd: str, **params: Any) -> dict[str, Any]:
        c = cmd.lower()
        if c == "tap":
            x, y = int(params["x"]), int(params["y"])
            self.adb.shell(f"input tap {x} {y}")
            return {"success": True, "backend": "adb_input"}
        if c == "swipe":
            x1, y1 = int(params["x1"]), int(params["y1"])
            x2, y2 = int(params["x2"]), int(params["y2"])
            dur = int(params.get("duration", 300))
            self.adb.shell(f"input swipe {x1} {y1} {x2} {y2} {dur}")
            return {"success": True, "backend": "adb_input"}
        if c == "type":
            text = str(params.get("text", "")).replace(" ", "%s").replace("'", "")
            self.adb.shell(f"input text '{text}'")
            return {"success": True, "backend": "adb_input"}
        if c == "global":
            act = str(params.get("action", "")).upper()
            keymap = {
                "BACK": "KEYCODE_BACK",
                "HOME": "KEYCODE_HOME",
                "RECENTS": "KEYCODE_APP_SWITCH",
                "ENTER": "KEYCODE_ENTER",
            }
            keycode = keymap.get(act, act)
            self.adb.shell(f"input keyevent {keycode}")
            return {"success": True, "backend": "adb_input"}
        return {"success": False, "error": f"Unsupported fallback action: {cmd}"}

    def dump_compact_ui(self, *, max_elements: int = 60) -> dict[str, Any]:
        """Return a token-efficient compact list of interactive/labelled UI elements on screen."""
        xml_str = ""
        backend = "helper"
        fg = self.adb.foreground_app()

        if self.ensure_ready():
            try:
                port = self._ensure_forward()
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/hierarchy.xml",
                    headers={"X-Artemis-Token": self._token},
                    method="GET",
                )
                with urllib.request.urlopen(req, timeout=4.0) as resp:
                    xml_str = resp.read().decode("utf-8", errors="replace")
            except Exception:
                xml_str = ""

        if not xml_str or "<hierarchy" not in xml_str:
            backend = "uiautomator"
            self.adb.shell("uiautomator dump /sdcard/agentdroid_ui.xml >/dev/null 2>&1 || true")
            xml_str = self.adb.shell("cat /sdcard/agentdroid_ui.xml 2>/dev/null || true")

        elements: list[dict[str, Any]] = []
        if xml_str and "<" in xml_str:
            try:
                xml_clean = xml_str[xml_str.find("<") :]
                root = ET.fromstring(xml_clean)
                idx = 1
                for node in root.iter():
                    text = (node.attrib.get("text") or "").strip()
                    desc = (node.attrib.get("content-desc") or "").strip()
                    res_id = (node.attrib.get("resource-id") or "").strip()
                    clickable = node.attrib.get("clickable") == "true"
                    editable = "EditText" in (node.attrib.get("class") or "")
                    bounds_str = node.attrib.get("bounds") or ""

                    if not (text or desc or clickable or editable):
                        continue

                    m = re.match(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", bounds_str)
                    if not m:
                        continue
                    x1, y1, x2, y2 = map(int, m.groups())
                    if x2 <= x1 or y2 <= y1:
                        continue
                    cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
                    short_id = res_id.split("/")[-1] if "/" in res_id else res_id
                    short_cls = (node.attrib.get("class") or "").rsplit(".", 1)[-1]

                    label = text or desc or short_id or short_cls
                    item: dict[str, Any] = {
                        "id": idx,
                        "label": label[:100],
                        "class": short_cls,
                        "center": [cx, cy],
                    }
                    if text and desc and text != desc:
                        item["desc"] = desc[:80]
                    if short_id and short_id != label:
                        item["resource_id"] = short_id
                    if clickable:
                        item["clickable"] = True
                    if editable:
                        item["editable"] = True
                    elements.append(item)
                    idx += 1
                    if len(elements) >= max_elements:
                        break
            except Exception as exc:
                return {
                    "backend": backend,
                    "foreground": fg,
                    "element_count": 0,
                    "elements": [],
                    "parse_error": str(exc),
                }

        return {
            "backend": backend,
            "foreground": fg,
            "element_count": len(elements),
            "elements": elements,
        }
