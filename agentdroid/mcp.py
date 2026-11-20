"""Native Model Context Protocol (MCP) Server for AgentDroid.

Connects Claude Code, Codex, Antigravity, and Cursor directly to the
connected Android device via standard MCP over stdio JSON-RPC.
Requires zero external dependencies.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import sys
import time
from typing import Any

from agentdroid.adb import AdbDevice
from agentdroid.engine import AndroidEngine

logger = logging.getLogger(__name__)

MCP_VERSION = "2024-11-05"
SERVER_NAME = "agentdroid"
SERVER_VERSION = "0.3.0"

TOOL_DEFINITIONS = [
    {
        "name": "mobile_run_workflow",
        "description": (
            "RECOMMENDED: Run a complete, compound Android task in ONE single call (zero token waste, "
            "no turn-by-turn latency). Handles app installation (F-Droid/URL/APK), pushing files, "
            "opening URLs/files, launching activities, executing chained UI steps ('click:#1', "
            "'fill:field=text', 'scroll:down', 'key:ENTER'), asserting text, taking screenshots, "
            "setting/reading clipboard, and pulling files back to the host machine. Returns structured "
            "JSON report with compact UI hierarchy."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "install": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "APKs or F-Droid package refs to install (e.g. ['fdroid:net.gsantner.markor']).",
                },
                "push": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to push in 'LOCAL:REMOTE' format (e.g. ['./test.md:/sdcard/Download/test.md']).",
                },
                "open_url": {
                    "type": "string",
                    "description": "URL, deep link, or local file to open (e.g. 'file:///sdcard/Download/test.md').",
                },
                "locked_app_package": {
                    "type": "string",
                    "description": "Optional Android package name to force-handle open_url intents (e.g. 'com.android.chrome').",
                },
                "launch": {
                    "type": "string",
                    "description": "App package or component to launch (e.g. 'net.gsantner.markor').",
                },
                "do": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered UI steps: 'click:<target|#id|btn:X|edit:X|exact:X>', 'fill:<sel>=<txt>', 'type:<txt>', 'append:<txt>', 'wait-text:<txt>[@sec]', 'wait-any:<a|b>[@sec]', 'wait-gone:<txt>[@sec]', 'wait-stable[@sec]', 'wait-change[@sec]', 'if-visible:<needle>-><step>', 'capture:<var>=<regex>', 'capture-all:<var>=<regex>', 'hide-keyboard', 'scroll:down', 'scroll-to:<txt>', 'key:<KEY>', 'tap:x,y', 'sleep:<sec>'. Supports {{var}} interpolation.",
                },
                "pull": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files to pull back in 'REMOTE:LOCAL' format.",
                },
                "set_clipboard": {
                    "type": "string",
                    "description": "Text to write to the Android clipboard.",
                },
                "get_clipboard": {
                    "type": "boolean",
                    "description": "Whether to return the Android clipboard contents.",
                },
                "screenshot": {
                    "type": "string",
                    "description": "Optional host path for final screenshot. DO NOT pass unless hierarchy returned zero readable controls or user explicitly requested an image.",
                },
                "wait_text": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Wait (polling UI hierarchy every 0.2s, zero screenshots) for text strings to appear before assertions and UI dump.",
                },
                "assert_text": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Text strings that must be visible on screen before finishing.",
                },
                "notifications": {
                    "type": "boolean",
                    "description": "Whether to read active Android notifications.",
                },
                "watch": {
                    "type": "boolean",
                    "default": False,
                    "description": "If True, opens the live floating simulator overlay window for user viewing.",
                },
            },
        },
    },
    {
        "name": "mobile_get_device_state",
        "description": (
            "Retrieve real-time Android device state. ALWAYS prefer view_type='hierarchy' "
            "([#1] Button 'Settings' | Center: (x, y), ~5ms, ~150 tokens). NEVER request "
            "'screenshot' unless 'hierarchy' shows 0 actionable controls after settling "
            "(raw image/Canvas/game) or the user explicitly asked for an image."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "view_type": {
                    "type": "string",
                    "enum": ["hierarchy", "screenshot", "both"],
                    "default": "hierarchy",
                    "description": "Observation type: 'hierarchy' (mandatory default: compact numbered elements), 'screenshot' (Canvas/image fallback only), or 'both'.",
                },
                "max_elements": {
                    "type": "integer",
                    "default": 80,
                    "description": "Maximum number of interactive elements to return.",
                },
                "include_ime": {
                    "type": "boolean",
                    "default": False,
                    "description": "Include soft-keyboard IME keys in hierarchy (default: False to filter noise).",
                },
            },
        },
    },
    {
        "name": "mobile_perform_action",
        "description": (
            "Perform a precise UI action on the Android device using Artemis's 'Dynamic-First, "
            "Coordinate-Fallback' pattern. Targets can be an element index ('#1'), exact/substring "
            "text ('Login'), resource ID ('btn_submit'), or coordinates ('540, 960')."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["click", "tap", "fill", "type", "key", "scroll", "swipe", "scroll_to"],
                    "description": "Action type to execute.",
                },
                "target": {
                    "type": "string",
                    "description": "Element selector: index ('#3'), text ('Sign In'), or coordinates ('500, 800').",
                },
                "coordinates": {
                    "description": "Optional coordinates for 'tap' as [x, y] or 'x, y', or for 'swipe' as [x1, y1, x2, y2].",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type or fill (required for 'fill' and 'type').",
                },
                "direction": {
                    "type": "string",
                    "enum": ["down", "up"],
                    "default": "down",
                    "description": "Direction for 'scroll' or 'scroll_to'.",
                },
            },
            "required": ["action"],
        },
    },
    {
        "name": "mobile_action_burst",
        "description": (
            "Execute a sequence of multiple UI actions in one fast burst without round-trip "
            "LLM latency. Example: ['click:#2', 'sleep:0.3', 'type:test@user.com', 'key:ENTER']."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "actions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of action strings: 'click:<sel|#id|btn:X|edit:X>', 'tap:x,y', 'fill:<sel>=<txt>', 'type:<txt>', 'append:<txt>', 'wait-text:<txt>[@sec]', 'wait-any:<a|b>[@sec]', 'wait-gone:<txt>[@sec]', 'wait-stable[@sec]', 'wait-change[@sec]', 'if-visible:<needle>-><step>', 'capture:<var>=<regex>', 'hide-keyboard', 'key:<KEY>', 'scroll:down', 'scroll-to:<txt>', 'sleep:<sec>'.",
                },
                "do": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Alias for actions. Ordered list of action strings.",
                },
            },
        },
    },
    {
        "name": "mobile_auto_dismiss_dialogs",
        "description": (
            "Detect and automatically dismiss standard Android system dialogs (permission "
            "prompts: 'Allow' / 'While using the app', ANR alerts: 'Wait' / 'Close app', etc.)."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mobile_launch_app",
        "description": "Launch an installed Android app by its package name or component.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "package": {
                    "type": "string",
                    "description": "Android package name (e.g. 'com.android.settings'). Also accepts 'package_name'.",
                },
                "package_name": {
                    "type": "string",
                    "description": "Alias for package.",
                },
            },
        },
    },
    {
        "name": "mobile_install_app",
        "description": "Install an APK from F-Droid ('fdroid:<pkg>'), an HTTPS URL, or a local file with optional SHA-256 verification and runtime permissions auto-granted.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "App source: 'fdroid:<pkg>', 'https://...apk', 'sha256:<hex>@https://...apk', or local file path.",
                },
                "sha256": {
                    "type": "string",
                    "description": "Optional expected 64-character lowercase SHA-256 hex checksum.",
                },
            },
            "required": ["source"],
        },
    },
    {
        "name": "mobile_open_url",
        "description": "Open a web URL or deep link (e.g. https://..., mailto:..., geo:...) in Android.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "URL or URI to open.",
                }
            },
            "required": ["url"],
        },
    },
    {
        "name": "mobile_read_notifications",
        "description": "Read active Android notifications (e.g. 2FA verification codes, SMS, OTPs).",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "mobile_clipboard",
        "description": "Read from or write to the Android device clipboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "If provided, copies this text to the device clipboard. If omitted, reads clipboard.",
                }
            },
        },
    },
    {
        "name": "mobile_diagnose",
        "description": "Diagnose ADB connection status, root access, silent provisioner, and accessibility helper reachability.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class McpServer:
    """Stdio JSON-RPC MCP Server."""

    def __init__(
        self,
        serial: str | None = None,
        *,
        safe_mode: bool | None = None,
        shell_allowlist: list[str] | tuple[str, ...] | str | None = None,
    ) -> None:
        self.adb = AdbDevice(
            serial=serial,
            safe_mode=safe_mode,
            shell_allowlist=shell_allowlist,
        )
        self.engine = AndroidEngine(self.adb)

    def handle_request(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        req_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_DEFINITIONS}}

        if method == "tools/call":
            tool_name = str(params.get("name") or "")
            args = params.get("arguments") or {}
            try:
                result_str = self._call_tool(tool_name, args)
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": result_str}],
                        "isError": False,
                    },
                }
            except Exception as exc:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True,
                    },
                }

        # Unknown method
        if req_id is not None:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Method '{method}' not found"},
            }
        return None

    def _call_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "mobile_run_workflow":
            from agentdroid.pipeline import CompoundPipeline, PipelineSpec

            spec = PipelineSpec.from_dict(args)
            if self.adb.safe_mode:
                spec.safe_mode = True
                spec.shell_allowlist = list(self.adb.shell_allowlist)
            pipeline = CompoundPipeline(spec)
            report = pipeline.run()
            return json.dumps(report, indent=2, ensure_ascii=False)

        if name == "mobile_get_device_state":
            vtype = args.get("view_type", "hierarchy")
            max_el = int(args.get("max_elements", 80))
            inc_ime = bool(args.get("include_ime", False))
            out: dict[str, Any] = {}

            if vtype in ("hierarchy", "both"):
                ui = self.engine.get_screen_data(max_elements=max_el, include_ime=inc_ime)
                out["foreground"] = ui.get("foreground")
                out["display_size"] = ui.get("display_size")
                out["element_count"] = ui.get("element_count")
                out["elements_formatted"] = ui.get("formatted_text")

            if vtype in ("screenshot", "both"):
                artifacts_dir = Path("./artifacts")
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                dest = artifacts_dir / f"screen_{int(time.time())}.png"
                self.adb.screenshot(str(dest))
                out["screenshot_path"] = str(dest.resolve())

            return json.dumps(out, indent=2, ensure_ascii=False)

        if name == "mobile_perform_action":
            act = args.get("action", "").lower()
            target = str(args.get("target") or "")
            text = str(args.get("text") or "")
            direction = args.get("direction", "down")
            action_dict: dict[str, Any] = {"type": act}
            if act in ("click", "fill"):
                action_dict["selector"] = target or text
                if text:
                    action_dict["text"] = text
            elif act == "tap":
                coords = args.get("coordinates")
                if coords is not None:
                    if isinstance(coords, (list, tuple)) and len(coords) >= 2:
                        action_dict["x"], action_dict["y"] = float(coords[0]), float(coords[1])
                    elif isinstance(coords, dict):
                        action_dict["x"], action_dict["y"] = float(coords.get("x", 0)), float(coords.get("y", 0))
                    elif isinstance(coords, str):
                        parts = [float(p.strip()) for p in coords.split(",") if p.strip()]
                        if len(parts) >= 2:
                            action_dict["x"], action_dict["y"] = parts[0], parts[1]
                elif "x" in args and "y" in args:
                    action_dict["x"], action_dict["y"] = float(args["x"]), float(args["y"])
                else:
                    parts = [float(p.strip()) for p in target.split(",") if p.strip()]
                    if len(parts) >= 2:
                        action_dict["x"], action_dict["y"] = parts[0], parts[1]
                    elif target:
                        action_dict["type"] = "click"
                        action_dict["selector"] = target
                if "x" not in action_dict and target:
                    action_dict["type"] = "click"
                    action_dict["selector"] = target
            elif act == "type":
                action_dict["text"] = text or target
                if target and target != action_dict["text"]:
                    action_dict["selector"] = target
            elif act == "key":
                action_dict["key"] = target or args.get("key") or text
            elif act in ("scroll", "scroll_to"):
                action_dict["direction"] = direction
                action_dict["text"] = target or text
            elif act == "swipe":
                coords = args.get("coordinates")
                pts: list[float] = []
                if isinstance(coords, (list, tuple)):
                    pts = [float(c) for c in coords]
                else:
                    pts = [float(p.strip()) for p in target.split(",") if p.strip()]
                if len(pts) >= 4:
                    action_dict["x1"], action_dict["y1"], action_dict["x2"], action_dict["y2"] = pts[:4]

            res = self.engine.execute_action(action_dict)
            return json.dumps(res, indent=2, ensure_ascii=False)

        if name == "mobile_action_burst":
            actions = args.get("actions") or args.get("do") or []
            if isinstance(actions, str):
                actions = [actions]
            res_list = self.engine.execute_action_burst(actions)
            return json.dumps(res_list, indent=2, ensure_ascii=False)

        if name == "mobile_auto_dismiss_dialogs":
            res = self.engine.auto_dismiss_dialogs()
            return json.dumps(res, indent=2, ensure_ascii=False)

        if name == "mobile_launch_app":
            package = args.get("package") or args.get("package_name") or args.get("pkg")
            if not package:
                raise ValueError("Missing 'package' parameter in mobile_launch_app")
            res = self.adb.launch_app(str(package))
            return json.dumps(res, indent=2, ensure_ascii=False)

        if name == "mobile_install_app":
            installed = self.adb.install_apk(
                args["source"],
                grant_permissions=True,
                expected_sha256=args.get("sha256"),
            )
            return json.dumps(installed.to_dict(), indent=2, ensure_ascii=False)

        if name == "mobile_open_url":
            res = self.adb.open_url(args["url"])
            return json.dumps(res, indent=2, ensure_ascii=False)

        if name == "mobile_read_notifications":
            notifs = self.adb.get_notifications()
            return json.dumps(notifs, indent=2, ensure_ascii=False)

        if name == "mobile_clipboard":
            text = args.get("text")
            if text:
                ok_clip = self.adb.set_clipboard(text)
                return json.dumps({"action": "set", "result": ok_clip}, indent=2)
            else:
                clip = self.adb.get_clipboard()
                return json.dumps({"clipboard": clip}, indent=2)

        if name == "mobile_diagnose":
            conn = self.adb.connect(timeout=5.0)
            is_root = self.adb.ensure_root() if conn else False
            silent_ok = self.adb.is_provisioned_silent() if conn else False
            ping = self.engine.helper.ping() if conn else None
            launcher_apps = self.adb.list_launcher_apps() if conn else []
            return json.dumps(
                {
                    "serial": self.adb.serial,
                    "connected": conn,
                    "root_adb": is_root,
                    "silent_provisioned": silent_ok,
                    "accessibility_helper": ping or {"reachable": False},
                    "installed_apps": launcher_apps,
                },
                indent=2,
            )

        raise ValueError(f"Unknown tool '{name}'")

    def run_stdio(self) -> None:
        """Run MCP stdio JSON-RPC loop reading from stdin and writing to stdout."""
        # Ensure stdout is unbuffered utf-8
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue

            # Support Content-Length prefix if present
            if line.startswith("Content-Length:"):
                # Read header and empty line
                try:
                    length = int(line.split(":", 1)[1].strip())
                    sys.stdin.readline()  # consume empty line
                    raw_data = sys.stdin.read(length)
                    req = json.loads(raw_data)
                except (ValueError, json.JSONDecodeError) as exc:
                    logger.debug("Skipping malformed Content-Length MCP frame: %s", exc)
                    continue
            else:
                try:
                    req = json.loads(line)
                except json.JSONDecodeError as exc:
                    logger.debug("Skipping malformed JSON-RPC line: %s", exc)
                    continue

            resp = self.handle_request(req)
            if resp is not None:
                out_bytes = json.dumps(resp, ensure_ascii=False) + "\n"
                sys.stdout.write(out_bytes)
                sys.stdout.flush()


def install_mcp_config(target_agent: str = "all") -> dict[str, list[str]]:
    """Configure Claude Code, Codex, Antigravity, and Cursor to use agentdroid MCP."""
    home = Path.home()
    installed = []

    # 1. Antigravity / Gemini CLI (`agy`) & Gemini Config
    if target_agent in ("all", "antigravity", "gemini", "agy"):
        import shutil, subprocess
        agy_bin = shutil.which("agy")
        if agy_bin:
            try:
                proc = subprocess.run(
                    [agy_bin, "mcp", "add", "agentdroid", "agentdroid", "mcp"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if proc.returncode == 0:
                    installed.append("agy mcp (Antigravity CLI)")
            except (OSError, subprocess.SubprocessError) as exc:
                logger.debug("Failed registering agy mcp: %s", exc)

        gemini_cfg = home / ".gemini" / "config" / "mcp_config.json"
        try:
            gemini_cfg.parent.mkdir(parents=True, exist_ok=True)
            data: dict[str, Any] = {}
            if gemini_cfg.is_file():
                try:
                    data = json.loads(gemini_cfg.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
            servers = data.setdefault("mcpServers", {})
            servers["agentdroid"] = {
                "command": "agentdroid",
                "args": ["mcp"],
                "env": {"PYTHONUNBUFFERED": "1"},
            }
            gemini_cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            installed.append(str(gemini_cfg))

            # Sync schema caches for Antigravity lazy-loaded tools
            for mcp_cache_dir in [
                home / ".gemini" / "antigravity-cli" / "mcp" / "agentdroid",
                home / ".gemini" / "antigravity" / "mcp" / "agentdroid",
            ]:
                if mcp_cache_dir.is_dir():
                    for tool in TOOL_DEFINITIONS:
                        tool_file = mcp_cache_dir / f"{tool['name']}.json"
                        t_data = {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool["inputSchema"],
                        }
                        tool_file.write_text(json.dumps(t_data, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            logger.debug("Failed writing %s: %s", gemini_cfg, exc)

    # 2. Codex CLI (~/.codex/config.toml)
    if target_agent in ("all", "codex"):
        codex_cfg = home / ".codex" / "config.toml"
        try:
            codex_cfg.parent.mkdir(parents=True, exist_ok=True)
            text = codex_cfg.read_text(encoding="utf-8") if codex_cfg.is_file() else ""
            if "[mcp_servers.agentdroid]" not in text:
                block = '\n[mcp_servers.agentdroid]\ncommand = "agentdroid"\nargs = ["mcp"]\n'
                codex_cfg.write_text(text + block, encoding="utf-8")
            installed.append(str(codex_cfg))
        except OSError as exc:
            logger.debug("Failed writing %s: %s", codex_cfg, exc)

    # 3. Claude Code (~/.claude.json)
    if target_agent in ("all", "claude"):
        claude_cfg = home / ".claude.json"
        try:
            data = {}
            if claude_cfg.is_file():
                try:
                    data = json.loads(claude_cfg.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
            mcp_srv = data.setdefault("mcpServers", {})
            mcp_srv["agentdroid"] = {
                "command": "agentdroid",
                "args": ["mcp"],
            }
            claude_cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            installed.append(str(claude_cfg))
        except OSError as exc:
            logger.debug("Failed writing %s: %s", claude_cfg, exc)

    # 4. Cursor (.cursor/mcp.json)
    if target_agent in ("all", "cursor"):
        cursor_cfg = home / ".cursor" / "mcp.json"
        try:
            cursor_cfg.parent.mkdir(parents=True, exist_ok=True)
            data = {}
            if cursor_cfg.is_file():
                try:
                    data = json.loads(cursor_cfg.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    data = {}
            mcp_srv = data.setdefault("mcpServers", {})
            mcp_srv["agentdroid"] = {
                "command": "agentdroid",
                "args": ["mcp"],
            }
            cursor_cfg.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            installed.append(str(cursor_cfg))
        except OSError as exc:
            logger.debug("Failed writing %s: %s", cursor_cfg, exc)

    return {"installed": installed}
