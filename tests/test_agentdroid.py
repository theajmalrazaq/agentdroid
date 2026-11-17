"""Tests for the AgentDroid (agentdroid) CLI, compound pipeline, and general-purpose helpers."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agentdroid.adb import AdbDevice, CrashReport, InstalledAppInfo
from agentdroid.cli import build_parser, normalize_argv
from agentdroid.pipeline import CompoundPipeline, PipelineSpec


class TestCliNormalizationAndParsing(unittest.TestCase):
    def test_normalize_shorthand_to_run(self) -> None:
        argv = ["agentdroid", "--headless", "-i", "fdroid:markor", "Open Markor and create a note"]
        normalized = normalize_argv(argv)
        self.assertEqual(normalized[1], "run")
        self.assertIn("--headless", normalized)

    def test_known_subcommands_preserved(self) -> None:
        for sub in ("run", "watch", "up", "down", "provision", "app", "device", "ui", "pipeline", "doctor", "mcp"):
            self.assertEqual(normalize_argv(["agentdroid", sub])[1], sub)

    def test_parse_compound_run_flags(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "--headless",
                "-i",
                "fdroid:org.mozilla.fennec_fdroid",
                "--push",
                "./doc.pdf:/sdcard/Download/doc.pdf",
                "--open-url",
                "https://news.ycombinator.com",
                "--pull",
                "/sdcard/Download/out.txt:./artifacts/out.txt",
                "--notifications",
                "--get-clipboard",
                "--dump-ui",
                "--json",
            ]
        )
        self.assertEqual(args.install, ["fdroid:org.mozilla.fennec_fdroid"])
        self.assertEqual(args.push, ["./doc.pdf:/sdcard/Download/doc.pdf"])
        self.assertEqual(args.open_url, ["https://news.ycombinator.com"])
        self.assertTrue(args.notifications)
        self.assertTrue(args.get_clipboard)
        self.assertTrue(args.dump_ui)
        self.assertTrue(args.json)

    def test_interleaved_ui_actions_preserve_exact_order(self) -> None:
        from agentdroid.cli import _parse_ui_actions, build_parser

        parser = build_parser()
        args = parser.parse_args(
            [
                "run",
                "--click",
                "Open from storage",
                "--click",
                "notes.md",
                "--click",
                "Edit",
                "--type",
                "Appended text\n",
                "--click",
                "Save",
                "-d",
                "key:BACK",
            ]
        )
        actions = _parse_ui_actions(args)
        expected = [
            {"type": "click", "selector": "Open from storage"},
            {"type": "click", "selector": "notes.md"},
            {"type": "click", "selector": "Edit"},
            {"type": "type", "text": "Appended text\n"},
            {"type": "click", "selector": "Save"},
            {"type": "key", "key": "BACK"},
        ]
        self.assertEqual(actions, expected)


class TestCompoundPipelineExecution(unittest.TestCase):
    def test_compound_general_purpose_pipeline_single_call(self) -> None:
        spec = PipelineSpec(
            serial="127.0.0.1:5555",
            headless=True,
            auto_provision=True,
            push_files=["/tmp/in.txt:/sdcard/Download/in.txt"],
            install_apks=["fdroid:net.gsantner.markor"],
            launch_target="auto",
            open_urls=["https://example.com"],
            pull_files=["/sdcard/Download/out.txt:/tmp/out.txt"],
            get_clipboard=True,
            read_notifications=True,
            check_crashes=True,
            dump_ui=True,
        )
        pipeline = CompoundPipeline(spec)

        pipeline.adb.connect = MagicMock(return_value=True)
        pipeline.adb.provision_silent = MagicMock(
            return_value={"provisioned": True, "action": "already_provisioned", "serial": "127.0.0.1:5555"}
        )
        pipeline.adb.clear_logs = MagicMock()
        pipeline.adb.push_file = MagicMock(
            return_value={"local": "/tmp/in.txt", "remote": "/sdcard/Download/in.txt", "ok": True}
        )
        pipeline.adb.install_apk = MagicMock(
            return_value=InstalledAppInfo(
                source="fdroid:net.gsantner.markor",
                local_path="/tmp/markor.apk",
                package="net.gsantner.markor",
                main_activity="net.gsantner.markor/.activity.MainActivity",
                permissions_granted=4,
                appops_granted=9,
                duration_sec=1.2,
            )
        )
        pipeline.adb.launch_app = MagicMock(
            return_value={
                "launched": True,
                "package": "net.gsantner.markor",
                "component": "net.gsantner.markor/.activity.MainActivity",
                "output": "Status: ok",
            }
        )
        pipeline.adb.open_url = MagicMock(
            return_value={"opened": True, "uri": "https://example.com", "package": None, "output": "ok"}
        )
        pipeline.adb.pull_file = MagicMock(
            return_value={"remote": "/sdcard/Download/out.txt", "local": "/tmp/out.txt", "ok": True}
        )
        pipeline.adb.get_clipboard = MagicMock(return_value="copied-link")
        pipeline.adb.get_notifications = MagicMock(
            return_value=[{"package": "com.messaging", "title": "OTP", "text": "Your code is 482910"}]
        )
        pipeline.adb.collect_crashes = MagicMock(return_value=CrashReport(has_crashes=False))
        pipeline.helper.dump_compact_ui = MagicMock(
            return_value={
                "backend": "helper",
                "foreground": {"package": "net.gsantner.markor", "activity": ".MainActivity"},
                "element_count": 1,
                "elements": [{"id": 1, "label": "Save", "class": "Button", "center": [540, 960]}],
            }
        )

        report = pipeline.run()
        self.assertTrue(report["ok"])
        self.assertEqual(report["mode"], "headless")
        self.assertEqual(len(report["pushed_files"]), 1)
        self.assertEqual(report["installed_apks"][0]["package"], "net.gsantner.markor")
        self.assertEqual(report["launched_app"]["package"], "net.gsantner.markor")
        self.assertEqual(report["opened_urls"][0]["uri"], "https://example.com")
        self.assertEqual(len(report["pulled_files"]), 1)
        self.assertEqual(report["clipboard"], "copied-link")
        self.assertEqual(report["notifications"][0]["text"], "Your code is 482910")
        self.assertFalse(report["crashes"]["has_crashes"])
        self.assertEqual(report["ui_summary"]["element_count"], 1)

    def test_semantic_ui_actions_zero_env(self) -> None:
        spec = PipelineSpec(
            serial="127.0.0.1:5555",
            headless=True,
            auto_provision=False,
            launch_target="com.android.settings",
            ui_actions=[
                {"type": "click", "selector": "Display"},
                {"type": "fill", "selector": "Search", "text": "Dark theme"},
                {"type": "scroll", "direction": "down"},
            ],
            dump_ui=True,
        )
        pipeline = CompoundPipeline(spec)
        pipeline.adb.connect = MagicMock(return_value=True)
        pipeline.adb.clear_logs = MagicMock()
        pipeline.adb.launch_app = MagicMock(return_value={"launched": True, "package": "com.android.settings"})
        pipeline.helper.tap_element = MagicMock(return_value={"success": True, "selector": "Display"})
        pipeline.helper.fill_element = MagicMock(return_value={"success": True, "selector": "Search"})
        pipeline.helper.scroll = MagicMock(return_value={"success": True, "direction": "down"})
        pipeline.adb.collect_crashes = MagicMock(return_value=CrashReport(has_crashes=False))
        pipeline.helper.dump_compact_ui = MagicMock(
            return_value={
                "backend": "helper",
                "element_count": 2,
                "elements": [
                    {"id": 1, "label": "Display", "class": "TextView", "center": [200, 300]},
                    {"id": 2, "label": "Dark theme", "class": "Switch", "center": [500, 300]},
                ],
            }
        )

        report = pipeline.run()
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["ui_actions_executed"]), 3)
        self.assertEqual(report["ui_summary"]["element_count"], 2)


class TestOneCommandInstaller(unittest.TestCase):
    def test_install_agent_skills_and_rules_idempotent(self) -> None:
        from agentdroid.installer import ensure_cli_on_path, install_agent_skills_and_rules

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            mounted1 = install_agent_skills_and_rules(home_dir=fake_home)
            self.assertTrue(len(mounted1["skills_installed"]) >= 4)
            self.assertTrue(len(mounted1["rules_installed"]) >= 4)

            # Re-running should update in-place without duplicating marker blocks
            mounted2 = install_agent_skills_and_rules(home_dir=fake_home)
            self.assertEqual(len(mounted2["skills_installed"]), len(mounted1["skills_installed"]))
            codex_agents = (fake_home / ".codex" / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(codex_agents.count("<!-- AGENTDROID_RULES_START -->"), 1)

            cli_link = ensure_cli_on_path(home_dir=fake_home)
            self.assertTrue(Path(cli_link).exists())


class TestLiveWatcherSimulatorOverlay(unittest.TestCase):
    @patch("agentdroid.watcher.has_gui_display", return_value=True)
    @patch("shutil.which", return_value="/usr/bin/scrcpy")
    @patch("subprocess.Popen")
    def test_scrcpy_simulator_overlay_cmd_arguments(
        self, mock_popen: MagicMock, mock_which: MagicMock, mock_display: MagicMock
    ) -> None:
        from agentdroid.watcher import LiveWatcher

        mock_proc = MagicMock()
        mock_proc.pid = 9999
        mock_popen.return_value = mock_proc

        watcher = LiveWatcher(
            serial="127.0.0.1:5555",
            watch=True,
            always_on_top=True,
            window_width=412,
            window_height=892,
            window_x=100,
            window_y=200,
            borderless=True,
            interactive_control=False,
        )
        info = watcher.start()
        self.assertEqual(info["mode"], "watch")
        self.assertEqual(info["viewer"], "scrcpy_overlay")

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        self.assertIn("--always-on-top", cmd)
        self.assertIn("--window-borderless", cmd)
        self.assertIn("--window-width", cmd)
        self.assertEqual(cmd[cmd.index("--window-width") + 1], "412")
        self.assertIn("--window-height", cmd)
        self.assertIn("--no-audio", cmd)
        self.assertIn("--no-control", cmd)
        self.assertNotIn("--stay-awake", cmd)



class TestArtemisEngineAndMcp(unittest.TestCase):
    def test_engine_screen_data_formatting(self) -> None:
        from agentdroid.engine import AndroidEngine

        engine = AndroidEngine()
        engine.helper.dump_compact_ui = MagicMock(
            return_value={
                "backend": "helper",
                "foreground": "com.android.settings",
                "element_count": 2,
                "elements": [
                    {"id": 1, "label": "Network & internet", "class": "TextView", "center": [540, 400]},
                    {"id": 2, "label": "Connected devices", "class": "TextView", "center": [540, 600]},
                ],
            }
        )
        res = engine.get_screen_data()
        self.assertIn("[#1]", res["formatted_text"])
        self.assertIn("Network & internet", res["formatted_text"])
        self.assertIn("Center: (540, 400)", res["formatted_text"])
        self.assertIn("[#2]", res["formatted_text"])

    def test_engine_action_burst_execution(self) -> None:
        from agentdroid.engine import AndroidEngine

        engine = AndroidEngine()
        engine.helper.tap_element = MagicMock(return_value={"success": True, "selector": "#1"})
        engine.helper.action = MagicMock(return_value={"success": True})

        burst = ["click:#1", "sleep:0.1", "append:extra", "key:BACK"]
        results = engine.execute_action_burst(burst)
        self.assertEqual(len(results), 4)
        self.assertTrue(results[0]["result"]["success"])
        engine.helper.action.assert_any_call("type", text="extra", append=True)

    def test_engine_wait_text_step_and_fast_poll(self) -> None:
        from agentdroid.engine import AndroidEngine, parse_do_step

        self.assertEqual(parse_do_step("wait-text:Driving Mode"), {"type": "wait_text", "text": "Driving Mode"})
        self.assertEqual(parse_do_step("append:line"), {"type": "type", "text": "line", "append": True})

        engine = AndroidEngine()
        engine.helper.dump_compact_ui = MagicMock(
            side_effect=[
                {"elements": [{"id": 1, "label": "mapsWebView"}]},
                {"elements": [{"id": 10, "label": "Driving Mode 2h 51m"}]},
            ]
        )
        with patch("agentdroid.engine.time.sleep") as mock_sleep:
            res = engine.execute_action(parse_do_step("wait-text:Driving Mode"))
        self.assertTrue(res["success"])
        self.assertEqual(engine.helper.dump_compact_ui.call_count, 2)
        engine.helper.dump_compact_ui.assert_any_call(max_elements=100, allow_sparse_fallback=False)
        mock_sleep.assert_called_once_with(0.2)

    def test_mcp_server_protocol_initialize_and_tools(self) -> None:
        from agentdroid.mcp import McpServer

        server = McpServer()
        # 1. Initialize
        init_resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(init_resp["result"]["serverInfo"]["name"], "agentdroid")

        # 2. Tools list
        tools_resp = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = tools_resp["result"]["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("mobile_run_workflow", tool_names)
        self.assertIn("mobile_get_device_state", tool_names)
        self.assertIn("mobile_perform_action", tool_names)
        self.assertIn("mobile_action_burst", tool_names)
        self.assertIn("mobile_auto_dismiss_dialogs", tool_names)
        tools_by_name = {t["name"]: t for t in tools}
        self.assertIn("wait_text", tools_by_name["mobile_run_workflow"]["inputSchema"]["properties"])
        self.assertIn("append:", tools_by_name["mobile_run_workflow"]["inputSchema"]["properties"]["do"]["description"])
        self.assertIn("NEVER request 'screenshot'", tools_by_name["mobile_get_device_state"]["description"])

        # 3. Tool call - device state
        server.engine.helper.dump_compact_ui = MagicMock(
            return_value={"foreground": "com.android.settings", "element_count": 1, "elements": []}
        )
        call_resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "mobile_get_device_state", "arguments": {"view_type": "hierarchy"}},
        })
        self.assertFalse(call_resp["result"]["isError"])
        self.assertIn("com.android.settings", call_resp["result"]["content"][0]["text"])

        # 4. Tool call - mobile_install_app
        server.adb.install_apk = MagicMock(
            return_value=InstalledAppInfo(
                source="fdroid:net.gsantner.markor",
                local_path="/tmp/markor.apk",
                package="net.gsantner.markor",
                main_activity="net.gsantner.markor/.MainActivity",
                permissions_granted=3,
                appops_granted=5,
                duration_sec=0.5,
            )
        )
        install_resp = server.handle_request({
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "mobile_install_app", "arguments": {"source": "fdroid:net.gsantner.markor"}},
        })
        self.assertFalse(install_resp["result"]["isError"])
        self.assertIn("net.gsantner.markor", install_resp["result"]["content"][0]["text"])

    def test_mcp_install_configs_idempotent(self) -> None:
        from agentdroid.mcp import install_mcp_config

        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(Path, "home", return_value=Path(tmp)):
                res = install_mcp_config("all")
                self.assertGreaterEqual(len(res["installed"]), 3)
                # Verify .claude.json was written
                claude_file = Path(tmp) / ".claude.json"
                self.assertTrue(claude_file.is_file())
                self.assertIn("agentdroid", claude_file.read_text())


class TestInputDaemonAndContainerConfig(unittest.TestCase):
    def test_input_daemon_dex_generation_and_checksums(self) -> None:
        import hashlib
        import importlib.util
        import struct
        import zlib

        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "scripts" / "build_input_daemon_dex.py"
        spec = importlib.util.spec_from_file_location("build_input_daemon_dex", script_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        dex = mod.build_input_daemon_dex()
        self.assertTrue(dex.startswith(b"dex\n035\x00"))
        self.assertIn(b"Lcom/agentdroid/InputDaemon;", dex)
        file_size = struct.unpack_from("<I", dex, 32)[0]
        self.assertEqual(file_size, len(dex))
        stored_sha1 = dex[12:32]
        self.assertEqual(stored_sha1, hashlib.sha1(dex[32:]).digest())
        stored_adler = struct.unpack_from("<I", dex, 8)[0]
        self.assertEqual(stored_adler, zlib.adler32(dex[12:]) & 0xFFFFFFFF)

        committed = repo_root / "packages" / "agentdroid-input-daemon" / "agentdroid-input.dex"
        self.assertEqual(committed.read_bytes(), dex)

    def test_helper_input_daemon_persistent_socket_and_fallback(self) -> None:
        import socket
        import threading
        from agentdroid.helper import AccessibilityHelperClient, DEVICE_PORT, INPUT_DAEMON_PORT

        received: list[str] = []
        auth_failures_left = [1]

        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.bind(("127.0.0.1", 0))
        srv.listen(4)
        srv_port = srv.getsockname()[1]
        stop_flag = threading.Event()

        def serve() -> None:
            while not stop_flag.is_set():
                try:
                    srv.settimeout(0.1)
                    conn, _ = srv.accept()
                except TimeoutError:
                    continue
                except OSError:
                    break
                with conn:
                    rf = conn.makefile("r", encoding="utf-8")
                    while not stop_flag.is_set():
                        line = rf.readline()
                        if not line:
                            break
                        received.append(line.strip())
                        parts = line.strip().split("\t")
                        if auth_failures_left[0] > 0 and parts[1] != "ping":
                            auth_failures_left[0] -= 1
                            conn.sendall(b"ERR auth\n")
                        elif len(parts) >= 2 and parts[1] == "ping":
                            conn.sendall(b"OK pong\n")
                        else:
                            conn.sendall(b"OK\n")

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        try:
            mock_adb = MagicMock()
            mock_adb.serial = "127.0.0.1:5555"
            mock_adb.run_adb.return_value = MagicMock(returncode=0, stdout=f"127.0.0.1:5555 tcp:{srv_port} tcp:{INPUT_DAEMON_PORT}\n")

            helper = AccessibilityHelperClient(mock_adb)
            helper._token = "deadbeef" * 6
            helper._request = MagicMock(side_effect=AssertionError("Artemis HTTP should not be hit for tap"))
            helper._ensure_input_daemon = MagicMock(return_value=True)

            # First tap sees ERR auth once, triggers _ensure_input_daemon(force=True), retries, and succeeds
            res_tap = helper.action("tap", x=540, y=1200)
            self.assertTrue(res_tap["success"])
            self.assertEqual(res_tap["backend"], "input_daemon")
            self.assertEqual(res_tap["center"], [540, 1200])
            helper._ensure_input_daemon.assert_called_once_with(force=True)

            # Zero-coordinate swipe preserves 0.00 (no `or` truthiness bug)
            res_swipe = helper.action("swipe", x1=0, y1=100, x2=0, y2=900, duration=250)
            self.assertTrue(res_swipe["success"])
            self.assertEqual(res_swipe["backend"], "input_daemon")
            self.assertTrue(any("\tswipe\t0.00\t100.00\t0.00\t900.00\t250" in line for line in received))

            # Long press routed cleanly via InputDaemon
            res_lp = helper.action("long_press", x=100, y=200, duration=800)
            self.assertTrue(res_lp["success"])
            self.assertEqual(res_lp["backend"], "input_daemon")

            # Global key still routes to Artemis /action first when ready
            helper.ensure_ready = MagicMock(return_value=True)
            helper._request = MagicMock(return_value={"success": True})
            res_global = helper.action("global", action="HOME")
            self.assertTrue(res_global["success"])
            self.assertEqual(res_global["backend"], "helper_ipc")

            # If Artemis /action fails on global or type, falls back to InputDaemon
            helper._request = MagicMock(side_effect=RuntimeError("helper down"))
            res_global_fb = helper.action("global", action="RECENTS")
            self.assertTrue(res_global_fb["success"])
            self.assertEqual(res_global_fb["backend"], "input_daemon")
            self.assertEqual(res_global_fb["keycode"], "KEYCODE_APP_SWITCH")

            res_type_fb = helper.action("type", text="hello world", append=False)
            self.assertTrue(res_type_fb["success"])
            self.assertEqual(res_type_fb["backend"], "input_daemon")

            # append=True fallback also routes through InputDaemon (no slow adb input text fork)
            res_type_append_fb = helper.action("type", text="\nappended", append=True)
            self.assertTrue(res_type_append_fb["success"])
            self.assertEqual(res_type_append_fb["backend"], "input_daemon")

            # When InputDaemon forward is unreachable, tap falls back to adb_input
            helper.close()
            helper._input_local_port = None
            helper.ensure_ready = MagicMock(return_value=False)
            mock_adb.run_adb.return_value = MagicMock(returncode=1, stdout="", stderr="offline")
            res_adb = helper.action("tap", x=10, y=20)
            self.assertEqual(res_adb["backend"], "adb_input")
            mock_adb.shell.assert_called_with("input tap 10 20")
            self.assertEqual(DEVICE_PORT, 18888)
        finally:
            stop_flag.set()
            srv.close()
            t.join(timeout=1.0)

    def test_input_daemon_timeout_does_not_double_retry(self) -> None:
        from agentdroid.helper import AccessibilityHelperClient

        mock_adb = MagicMock()
        mock_adb.serial = "127.0.0.1:5555"
        helper = AccessibilityHelperClient(mock_adb)
        helper._input_local_port = 18889
        helper._send_input_cmd_locked = MagicMock(side_effect=TimeoutError("timed out"))
        helper._ensure_input_daemon = MagicMock(return_value=True)

        res = helper._input_daemon_exec("tap\t100\t200", timeout=1.0)
        self.assertIsNone(res)
        helper._send_input_cmd_locked.assert_called_once()
        helper._ensure_input_daemon.assert_not_called()

    def test_dump_compact_ui_uses_ping_foreground_without_adb(self) -> None:
        from agentdroid.helper import AccessibilityHelperClient

        mock_adb = MagicMock()
        mock_adb.serial = "127.0.0.1:5555"
        helper = AccessibilityHelperClient(mock_adb)
        helper._ensure_forward = MagicMock(return_value=18888)

        # Ensure ping() sets _last_ping via real ping logic or side_effect
        def fake_ping() -> dict[str, object]:
            data = {
                "success": True,
                "authenticated": True,
                "package": "org.fossify.math",
                "activity": "org.fossify.math.activities.MainActivity",
            }
            helper._last_ping = data
            return data

        helper.ping = fake_ping
        xml_body = b'<hierarchy rotation="0"><node text="7" class="android.widget.Button" clickable="true" bounds="[10,20][110,120]" /></hierarchy>'
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = xml_body

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ui = helper.dump_compact_ui(max_elements=20)

        self.assertEqual(ui["backend"], "helper")
        self.assertEqual(ui["element_count"], 1)
        self.assertEqual(
            ui["foreground"],
            {
                "package": "org.fossify.math",
                "activity": "org.fossify.math.activities.MainActivity",
                "component": "org.fossify.math/org.fossify.math.activities.MainActivity",
            },
        )
        mock_adb.foreground_app.assert_not_called()

        # When ping omits package, falls back to adb.foreground_app()
        def null_ping() -> dict[str, object]:
            data = {"success": True, "authenticated": True, "package": "null"}
            helper._last_ping = data
            return data

        helper.ping = null_ping
        mock_adb.foreground_app.return_value = {"package": "fallback.pkg", "activity": ".Act", "component": "fallback.pkg/.Act"}
        with patch("urllib.request.urlopen", return_value=mock_resp):
            ui2 = helper.dump_compact_ui(max_elements=20)
        self.assertEqual(ui2["foreground"]["package"], "fallback.pkg")
        mock_adb.foreground_app.assert_called_once()

        # When ping reports an IME/SoftInputWindow overlay, also falls back to adb.foreground_app()
        def ime_ping() -> dict[str, object]:
            data = {
                "success": True,
                "authenticated": True,
                "package": "com.android.inputmethod.latin",
                "activity": "android.view.View",
            }
            helper._last_ping = data
            return data

        helper.ping = ime_ping
        mock_adb.foreground_app.reset_mock()
        mock_adb.foreground_app.return_value = {"package": "net.gsantner.markor", "activity": ".DocumentActivity", "component": "net.gsantner.markor/.DocumentActivity"}
        with patch("urllib.request.urlopen", return_value=mock_resp):
            ui3 = helper.dump_compact_ui(max_elements=20)
        self.assertEqual(ui3["foreground"]["package"], "net.gsantner.markor")
        mock_adb.foreground_app.assert_called_once()

    def test_dump_compact_ui_sparse_webview_fallback_to_uiautomator(self) -> None:
        from agentdroid.helper import AccessibilityHelperClient

        mock_adb = MagicMock()
        mock_adb.serial = "127.0.0.1:5555"
        helper = AccessibilityHelperClient(mock_adb)
        helper._ensure_forward = MagicMock(return_value=18888)
        helper.ping = MagicMock(
            return_value={
                "success": True,
                "authenticated": True,
                "package": "us.spotco.maps",
                "activity": "us.spotco.maps.MainActivity",
            }
        )
        helper._last_ping = helper.ping.return_value

        sparse_xml = (
            b'<hierarchy rotation="0">'
            b'<node text="13:30" package="com.android.systemui" bounds="[22,0][139,66]" />'
            b'<node text="Tap to see quick actions" package="us.spotco.maps" clickable="true" bounds="[100,2100][980,2250]" />'
            b'</hierarchy>'
        )
        rich_uia_xml = (
            '<hierarchy rotation="0">'
            '<node text="Faisalabad, Pakistan to Lahore, Pakistan" package="us.spotco.maps" clickable="true" bounds="[100,120][980,220]" />'
            '<node text="Driving Mode 2h 50m" package="us.spotco.maps" clickable="true" bounds="[22,233][283,368]" />'
            '<node text="Two-wheeler Mode 3h 15m" package="us.spotco.maps" clickable="true" bounds="[280,233][541,368]" />'
            '</hierarchy>'
        )
        mock_adb.shell = MagicMock(side_effect=["", rich_uia_xml])
        mock_resp = MagicMock()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_resp.read.return_value = sparse_xml

        with patch("urllib.request.urlopen", return_value=mock_resp):
            ui = helper.dump_compact_ui(max_elements=80)

        self.assertEqual(ui["backend"], "uiautomator")
        self.assertEqual(ui["element_count"], 3)
        labels = [el["label"] for el in ui["elements"]]
        self.assertIn("Driving Mode 2h 50m", labels)

        # When allow_sparse_fallback=False and HTTP /hierarchy.xml is empty/unavailable, skips uiautomator block
        mock_adb.shell.reset_mock()
        with patch("urllib.request.urlopen", side_effect=TimeoutError("busy")):
            ui_fast = helper.dump_compact_ui(max_elements=80, allow_sparse_fallback=False)
        self.assertEqual(ui_fast["element_count"], 0)
        mock_adb.shell.assert_not_called()

    def test_adb_single_shell_boot_silent_probes_and_clear_logs(self) -> None:
        adb = AdbDevice("127.0.0.1:5555")
        adb.connect = MagicMock(return_value=True)
        adb.shell = MagicMock(
            side_effect=[
                "BOOT=1\npackage:/system/framework/framework-res.apk",
                "0.0\ncom.artemis.helper/.ArtemisAccessibilityService\n1",
                "0.0\ncom.artemis.helper/.ArtemisAccessibilityService\n0",
                "1.0\nnull\n1",
            ]
        )
        self.assertTrue(adb.wait_for_boot(timeout=2.0))
        self.assertTrue(adb.is_provisioned_silent())
        self.assertFalse(adb.is_provisioned_silent())
        self.assertFalse(adb.is_provisioned_silent())

        adb.run_adb = MagicMock(return_value=MagicMock(returncode=0))
        adb.clear_logs()
        adb.run_adb.assert_called_once_with(["logcat", "-b", "all", "-c"], timeout=10.0)

    def test_helper_ensure_ready_clears_stale_port_and_forces_reprovision(self) -> None:
        from agentdroid.helper import AccessibilityHelperClient

        mock_adb = MagicMock()
        mock_adb.serial = "127.0.0.1:5555"
        mock_adb.provision_silent.return_value = {"provisioned": True, "action": "already_provisioned"}
        helper = AccessibilityHelperClient(mock_adb)
        helper._local_port = 19999

        calls = {"n": 0}

        def ping_side_effect() -> dict[str, object] | None:
            calls["n"] += 1
            if calls["n"] == 1:
                helper._local_port = None
                return None
            return {"success": True, "authenticated": True}

        helper.ping = MagicMock(side_effect=ping_side_effect)
        self.assertTrue(helper.ensure_ready())
        mock_adb.provision_silent.assert_not_called()

        # When helper stays down despite already_provisioned, force=True is invoked once
        helper2 = AccessibilityHelperClient(mock_adb)
        helper2.ping = MagicMock(side_effect=[None] * 7 + [{"success": True, "authenticated": True}])
        with patch("time.sleep"):
            self.assertTrue(helper2.ensure_ready())
        self.assertEqual(mock_adb.provision_silent.call_count, 2)
        self.assertTrue(mock_adb.provision_silent.call_args_list[1].kwargs.get("force"))

    def test_container_sigkill_and_uinput_config_invariants(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        dockerfile = (repo_root / "docker" / "redroid" / "Dockerfile").read_text(encoding="utf-8")
        compose = (repo_root / "docker-compose.yml").read_text(encoding="utf-8")
        rc = (repo_root / "docker" / "redroid" / "agentdroid-touch.rc").read_text(encoding="utf-8")
        install_sh = (repo_root / "install.sh").read_text(encoding="utf-8")

        self.assertIn("STOPSIGNAL SIGKILL", dockerfile)
        self.assertIn("COPY --chmod=0644 docker/redroid/agentdroid-touch.rc", dockerfile)
        self.assertNotIn("COPY --chmod=0644 packages/", dockerfile)
        self.assertIn("agentdroid-input.dex", dockerfile)
        self.assertIn("agentdroid-touch.rc", dockerfile)
        self.assertIn("stop_signal: SIGKILL", compose)
        self.assertIn("stop_grace_period: 0s", compose)
        self.assertIn("/proc/misc", rc)
        self.assertIn("vendor.agentdroid_uinputd", rc)
        self.assertNotIn("restart zygote", rc)
        self.assertIn("modprobe uinput", install_sh)

    def test_probe_adbd_tcp_and_nonblocking_connect(self) -> None:
        import socket
        import threading
        from agentdroid.adb import probe_adbd_tcp

        # 1. Closed/immediate-EOF listener (like docker-proxy before adbd binds) -> False
        drop_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        drop_srv.bind(("127.0.0.1", 0))
        drop_srv.listen(2)
        drop_port = drop_srv.getsockname()[1]

        def drop_loop() -> None:
            while True:
                try:
                    c, _ = drop_srv.accept()
                    c.close()
                except OSError:
                    break

        t_drop = threading.Thread(target=drop_loop, daemon=True)
        t_drop.start()
        try:
            self.assertFalse(probe_adbd_tcp("127.0.0.1", drop_port, timeout=0.3))
        finally:
            drop_srv.close()
            t_drop.join(timeout=1.0)

        # 2. Active adbd-like listener replying CNXN -> True and checks 24-byte header + payload
        seen_magic: list[bytes] = []
        ok_srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        ok_srv.bind(("127.0.0.1", 0))
        ok_srv.listen(2)
        ok_port = ok_srv.getsockname()[1]

        def ok_loop() -> None:
            while True:
                try:
                    c, _ = ok_srv.accept()
                except OSError:
                    break
                with c:
                    data = c.recv(64)
                    seen_magic.append(data[:4])
                    c.sendall(b"CNXN" + b"\x00" * 20)

        t_ok = threading.Thread(target=ok_loop, daemon=True)
        t_ok.start()
        try:
            self.assertTrue(probe_adbd_tcp("127.0.0.1", ok_port, timeout=0.5))
            self.assertEqual(seen_magic, [b"CNXN"])
        finally:
            ok_srv.close()
            t_ok.join(timeout=1.0)

        # 3. AdbDevice.connect skips `adb connect` until probe_adbd_tcp succeeds
        adb = AdbDevice("127.0.0.1:5555")
        adb.is_connected = MagicMock(side_effect=[False, False, False, False, True])
        with patch("agentdroid.adb.probe_adbd_tcp", side_effect=[False, True]) as mock_probe, patch(
            "subprocess.run", return_value=MagicMock(returncode=0, stdout="connected to 127.0.0.1:5555", stderr="")
        ) as mock_run:
            self.assertTrue(adb.connect(timeout=5.0))
        self.assertEqual(mock_probe.call_count, 2)
        connect_calls = [c for c in mock_run.call_args_list if len(c.args[0]) >= 2 and c.args[0][1] == "connect"]
        self.assertEqual(len(connect_calls), 1)


class TestUniversalEngineAndRustParity(unittest.TestCase):
    def test_parse_xml_ime_filter_display_size_and_full_text_parity(self) -> None:
        import os
        from agentdroid.helper import AccessibilityHelperClient

        long_note = "Header " + ("x" * 210)
        xml = (
            '<hierarchy rotation="0">'
            '<node package="com.android.inputmethod.latin" class="android.inputmethodservice.Keyboard$Key" text="q" bounds="[0,2400][144,2600]" />'
            '<node package="org.demo" class="android.webkit.WebView" text="Search docs banner" bounds="[0,0][1440,3120]" />'
            f'<node package="org.demo" class="android.widget.EditText" text="{long_note}" clickable="true" bounds="[40,300][1400,900]" />'
            '<node package="org.demo" class="android.widget.Button" text="Search" clickable="true" resource-id="org.demo:id/btn_search" bounds="[1000,100][1380,220]" />'
            '</hierarchy>'
        )

        # Verify both Rust fast-path (when built) and pure-Python fallback
        for env_val in ("0", "1"):
            with patch.dict(os.environ, {"AGENTDROID_NO_RUST": env_val}):
                els, app_cnt, has_sys, disp, err = AccessibilityHelperClient._parse_hierarchy_xml(
                    xml, 80, include_ime=False
                )
                self.assertIsNone(err)
                self.assertEqual(disp, (1440, 3120))
                self.assertEqual(len(els), 3)  # IME Key filtered out
                self.assertEqual(app_cnt, 3)
                self.assertFalse(has_sys)
                edit_el = next(e for e in els if e["class"] == "EditText")
                self.assertEqual(edit_el.get("full_text"), long_note)

                els_ime, _, _, _, _ = AccessibilityHelperClient._parse_hierarchy_xml(
                    xml, 80, include_ime=True
                )
                self.assertEqual(len(els_ime), 4)

    def test_select_element_interactivity_and_prefixes(self) -> None:
        import os
        from agentdroid.helper import select_ui_element

        elements = [
            {"id": 1, "label": "Search results header", "class": "WebView", "center": [500, 100]},
            {"id": 2, "label": "Search", "class": "Button", "center": [900, 150], "resource_id": "btn_go", "clickable": True},
            {"id": 3, "label": "Search query", "class": "EditText", "center": [500, 300], "clickable": True, "editable": True},
        ]
        for env_val in ("0", "1"):
            with patch.dict(os.environ, {"AGENTDROID_NO_RUST": env_val}):
                self.assertEqual(select_ui_element(elements, "Search")["id"], 2)
                self.assertEqual(select_ui_element(elements, "btn:Search")["id"], 2)
                self.assertEqual(select_ui_element(elements, "btn:#1")["id"], 2)
                self.assertEqual(select_ui_element(elements, "edit:Search")["id"], 3)
                self.assertEqual(select_ui_element(elements, "edit:#1")["id"], 3)
                self.assertEqual(select_ui_element(elements, "id:btn_go")["id"], 2)
                self.assertEqual(select_ui_element(elements, "exact:Search")["id"], 2)
                self.assertEqual(select_ui_element(elements, "#1")["id"], 1)

    def test_wait_any_if_visible_and_capture_variable_interpolation(self) -> None:
        from agentdroid.engine import parse_do_step

        self.assertEqual(
            parse_do_step("wait-any:Ready|Allow|Error"),
            {"type": "wait_any", "patterns": ["Ready", "Allow", "Error"]},
        )
        self.assertEqual(parse_do_step("wait-gone:Spinner"), {"type": "wait_gone", "text": "Spinner"})
        self.assertEqual(parse_do_step("hide-keyboard"), {"type": "hide_keyboard"})

        spec = PipelineSpec.from_dict(
            {
                "serial": "127.0.0.1:5555",
                "auto_provision": False,
                "check_crashes": False,
                "do": [
                    "wait-any:Metric Ready|Offline",
                    "if-visible:Metric Ready->capture:eta=Metric Ready:\\s*([0-9]+\\s*min)",
                    "if-visible:MissingBanner->click:Nope",
                    "open-url:file:///sdcard/Download/out.md",
                    "append:- Result: {{eta}}",
                ],
                "assert_text": ["{{eta}}"],
            }
        )
        pipeline = CompoundPipeline(spec)
        pipeline.adb.connect = MagicMock(return_value=True)
        pipeline.adb.open_url = MagicMock(return_value={"opened": True, "uri": "file:///sdcard/Download/out.md"})
        pipeline.helper.action = MagicMock(return_value={"success": True, "backend": "helper_ipc"})
        pipeline.helper.dump_compact_ui = MagicMock(
            side_effect=[
                {"elements": [{"id": 1, "label": "Loading..."}]},
                {"elements": [{"id": 1, "label": "Metric Ready: 42 min"}]},
                {"elements": [{"id": 1, "label": "Metric Ready: 42 min"}]},
                {"elements": [{"id": 1, "label": "Metric Ready: 42 min"}]},
                {"elements": [{"id": 1, "label": "Metric Ready: 42 min"}]},
                {"elements": [{"id": 1, "label": "- Result: 42 min"}]},
                {"elements": [{"id": 1, "label": "- Result: 42 min"}]},
            ]
        )

        with patch("agentdroid.engine.time.sleep"):
            report = pipeline.run()

        self.assertTrue(report["ok"])
        self.assertEqual(report["captured_vars"], {"eta": "42 min"})
        pipeline.helper.action.assert_any_call("type", text="- Result: 42 min", append=True)

    def test_dynamic_display_size_scaling(self) -> None:
        from agentdroid.engine import AndroidEngine

        engine = AndroidEngine(AdbDevice("127.0.0.1:5555"))
        engine.helper._display_size = (1440, 3120)
        engine.helper.action = MagicMock(return_value={"success": True})

        res_tap = engine.tap_percentage(50.0, 50.0)
        self.assertEqual(res_tap["x"], 720)
        self.assertEqual(res_tap["y"], 1560)

        engine.helper.scroll("down")
        engine.helper.action.assert_any_call("swipe", x1=720, y1=2028, x2=720, y2=624, duration=300)

    def test_pipeline_fast_ping_skips_provision_silent(self) -> None:
        spec = PipelineSpec(serial="127.0.0.1:5555", auto_provision=True, check_crashes=False, dump_ui=False)
        pipeline = CompoundPipeline(spec)
        pipeline.helper.ping = MagicMock(return_value={"success": True, "authenticated": True})
        with patch.object(AdbDevice, "provision_silent", side_effect=AssertionError("should be skipped")):
            report = pipeline.run()
        self.assertTrue(report["ok"])
        self.assertEqual(report["provision"]["action"], "already_provisioned_fast")

    def test_fast_dump_dex_generation_and_displays_xml_parity(self) -> None:
        import hashlib
        import importlib.util
        import os
        import struct
        import zlib
        from agentdroid.helper import AccessibilityHelperClient

        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "scripts" / "build_fast_dump_dex.py"
        spec = importlib.util.spec_from_file_location("build_fast_dump_dex", script_path)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        dex = mod.build_fast_dump_dex()
        self.assertTrue(dex.startswith(b"dex\n035\x00"))
        self.assertIn(b"Lcom/agentdroid/FastDump;", dex)
        self.assertEqual(struct.unpack_from("<I", dex, 32)[0], len(dex))
        self.assertEqual(dex[12:32], hashlib.sha1(dex[32:]).digest())
        self.assertEqual(struct.unpack_from("<I", dex, 8)[0], zlib.adler32(dex[12:]) & 0xFFFFFFFF)
        committed = repo_root / "packages" / "agentdroid-fast-dump" / "agentdroid-fast-dump.dex"
        self.assertEqual(committed.read_bytes(), dex)

        # Verify <displays><display><window><node .../></window></display></displays> XML parity in Rust & Python
        displays_xml = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<displays><display id="0">'
            '<window index="0" bounds="[0,0][1080,2400]">'
            '<node package="org.demo" class="android.widget.Button" text="Continue" clickable="true" bounds="[100,200][500,300]" />'
            '</window></display></displays>'
        )
        for env_val in ("0", "1"):
            with patch.dict(os.environ, {"AGENTDROID_NO_RUST": env_val}):
                els, app_cnt, _, disp, err = AccessibilityHelperClient._parse_hierarchy_xml(
                    displays_xml, 80, include_ime=False
                )
                self.assertIsNone(err)
                self.assertEqual(disp, (1080, 2400))
                self.assertEqual(app_cnt, 1)
                self.assertEqual(els[0]["label"], "Continue")

    def test_per_step_timeout_systemui_demotion_and_if_visible_case_insensitive(self) -> None:
        import os
        from agentdroid.engine import AndroidEngine, parse_do_step
        from agentdroid.helper import AccessibilityHelperClient, select_ui_element

        # 1. Per-step @sec timeout parsing
        self.assertEqual(parse_do_step("wait-text:Loaded@60"), {"type": "wait_text", "text": "Loaded", "timeout": 60.0})
        self.assertEqual(
            parse_do_step("wait-any:INSTALL|Open@45"),
            {"type": "wait_any", "patterns": ["INSTALL", "Open"], "timeout": 45.0},
        )
        self.assertEqual(
            parse_do_step("wait-gone:Fetching app repositories@90"),
            {"type": "wait_gone", "text": "Fetching app repositories", "timeout": 90.0},
        )
        self.assertEqual(parse_do_step("wait-stable@30"), {"type": "wait_stable", "timeout": 30.0})
        self.assertEqual(parse_do_step("wait-change"), {"type": "wait_change"})
        self.assertEqual(parse_do_step("wait-change@5"), {"type": "wait_change", "timeout": 5.0})
        self.assertEqual(parse_do_step("wait-change:8"), {"type": "wait_change", "timeout": 8.0})

        # 2 & 3. com.android.systemui status-bar demotion + resource_id in both Rust and Python
        xml = (
            '<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="0">'
            '<node package="com.android.systemui" class="android.widget.TextView" text="17:38" resource-id="com.android.systemui:id/clock" clickable="true" bounds="[0,0][100,40]" />'
            '<node package="org.fossify.math" class="android.widget.Button" text="1" resource-id="org.fossify.math:id/btn_1" clickable="true" bounds="[100,800][300,950]" />'
            '</hierarchy>'
        )
        for env_val in ("0", "1"):
            with patch.dict(os.environ, {"AGENTDROID_NO_RUST": env_val}):
                els, _, _, _, err = AccessibilityHelperClient._parse_hierarchy_xml(xml, 80, include_ime=False)
                self.assertIsNone(err)
                picked = select_ui_element(els, "1")
                self.assertIsNotNone(picked)
                self.assertEqual(picked["resource_id"], "btn_1")
                blob = AndroidEngine._elements_search_blob(els)
                self.assertIn("btn_1", blob)

    def test_daemon_socket_roundtrip(self) -> None:
        import tempfile
        import threading
        from agentdroid import daemon as daemon_mod
        from agentdroid.pipeline import PipelineSpec

        with tempfile.TemporaryDirectory() as td:
            sock_path = Path(td) / "daemon.sock"
            pid_path = Path(td) / "daemon.pid"
            with patch.object(daemon_mod, "DAEMON_SOCK_PATH", sock_path), patch.object(
                daemon_mod, "DAEMON_PID_PATH", pid_path
            ), patch.object(daemon_mod, "CACHE_DIR", Path(td)):
                t = threading.Thread(target=daemon_mod.serve_daemon, daemon=True)
                t.start()
                for _ in range(40):
                    if daemon_mod.daemon_status()["running"]:
                        break
                    import time as _time
                    _time.sleep(0.05)
                self.assertTrue(daemon_mod.daemon_status()["running"])
                fake_report = {"ok": True, "mode": "headless", "device": "127.0.0.1:5555"}
                with patch.object(daemon_mod.CompoundPipeline, "run", return_value=fake_report):
                    res = daemon_mod.run_via_daemon(PipelineSpec(serial="127.0.0.1:5555", dump_ui=False))
                self.assertEqual(res, fake_report)
                stopped = daemon_mod.stop_daemon()
                self.assertTrue(stopped["stopped"])
                t.join(timeout=2.0)


if __name__ == "__main__":
    unittest.main()



