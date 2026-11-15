"""Direct client for the on-device Artemis Accessibility Helper (127.0.0.1:18888) with UIAutomator fallback.

Provides sub-second UI hierarchy dumps, semantic element targeting (by text, content-desc,
resource-id, or element index), scrolling, and gesture injection so the host AI agent
(Claude Code, Antigravity, Codex, Cursor, etc.) can drive Android directly with zero API keys.
"""

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


class AccessibilityHelperClient:
    """Sub-second UI hierarchy, semantic locator, and gesture client backed by ArtemisAccessibilityHelper.apk."""

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
            res = self._request("POST", "/action", payload, timeout=5.0)
            if res.get("success"):
                return res
            return self._fallback_adb_action(cmd, **params)
        except Exception:
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
                "SEARCH": "KEYCODE_SEARCH",
                "DELETE": "KEYCODE_DEL",
                "TAB": "KEYCODE_TAB",
            }
            keycode = keymap.get(act, act if act.startswith("KEYCODE_") else f"KEYCODE_{act}")
            self.adb.shell(f"input keyevent {keycode}")
            return {"success": True, "backend": "adb_input"}
        return {"success": False, "error": f"Unsupported fallback action: {cmd}"}

    def find_element(self, selector: str, *, max_elements: int = 120) -> dict[str, Any] | None:
        """Locate a UI element on screen by index (#3), exact text/desc/id, or case-insensitive substring."""
        sel = selector.strip()
        ui = self.dump_compact_ui(max_elements=max_elements)
        elements = ui.get("elements") or []

        # 1. Match by element index (#3 or plain integer if 1..len)
        idx_str = sel[1:] if sel.startswith("#") else sel
        if idx_str.isdigit():
            target_id = int(idx_str)
            for el in elements:
                if el.get("id") == target_id:
                    return el

        sel_lower = sel.lower()
        # 2. Exact match on label, desc, or resource_id
        for el in elements:
            for field in ("label", "desc", "resource_id"):
                val = str(el.get(field) or "").strip()
                if val and val.lower() == sel_lower:
                    return el

        # 3. Case-insensitive substring match
        for el in elements:
            for field in ("label", "desc", "resource_id"):
                val = str(el.get(field) or "").strip()
                if val and sel_lower in val.lower():
                    return el

        return None

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
            time.sleep(0.5)
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
        time.sleep(0.25)
        type_res = self.action("type", text=text, append=False)
        if submit:
            time.sleep(0.15)
            self.action("global", action="ENTER")
        return {
            "success": bool(type_res.get("success", True)),
            "selector": selector,
            "text": text,
            "matched_element": tap_res.get("matched_element"),
        }

    def scroll(self, direction: str = "down") -> dict[str, Any]:
        """Perform a directional scroll gesture on the screen."""
        d = direction.strip().lower()
        if d == "down":
            return self.action("swipe", x1=540, y1=1450, x2=540, y2=450, duration=350)
        if d == "up":
            return self.action("swipe", x1=540, y1=450, x2=540, y2=1450, duration=350)
        if d == "left":
            return self.action("swipe", x1=900, y1=960, x2=180, y2=960, duration=300)
        if d == "right":
            return self.action("swipe", x1=180, y1=960, x2=900, y2=960, duration=300)
        return {"success": False, "error": f"Unknown scroll direction: {direction!r}"}

    def scroll_to_text(self, text_needle: str, *, max_scrolls: int = 8, direction: str = "down") -> dict[str, Any]:
        """Scroll until an element matching text_needle becomes visible on screen."""
        for attempt in range(max_scrolls + 1):
            el = self.find_element(text_needle)
            if el is not None:
                return {"success": True, "found": True, "scrolls": attempt, "element": el}
            if attempt < max_scrolls:
                self.scroll(direction)
                time.sleep(0.5)
        return {
            "success": False,
            "found": False,
            "scrolls": max_scrolls,
            "error": f"Text {text_needle!r} not found after {max_scrolls} scrolls",
        }

    def dump_compact_ui(self, *, max_elements: int = 80) -> dict[str, Any]:
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
