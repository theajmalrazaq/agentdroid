"""Tests for the AgentDroid (agentdroid) CLI, compound pipeline, and general-purpose helpers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agentdroid.adb import AdbDevice, CrashReport, InstalledAppInfo
from agentdroid.cli import build_parser, main, normalize_argv
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

        burst = ["click:#1", "sleep:0.1", "key:BACK"]
        results = engine.execute_action_burst(burst)
        self.assertEqual(len(results), 3)
        self.assertTrue(results[0]["result"]["success"])

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
        self.assertIn("mobile_get_device_state", tool_names)
        self.assertIn("mobile_perform_action", tool_names)
        self.assertIn("mobile_action_burst", tool_names)
        self.assertIn("mobile_auto_dismiss_dialogs", tool_names)

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


if __name__ == "__main__":
    unittest.main()



