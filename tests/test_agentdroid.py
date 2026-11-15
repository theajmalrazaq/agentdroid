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
        for sub in ("run", "watch", "up", "down", "provision", "app", "device", "ui", "pipeline", "doctor"):
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
        self.assertEqual(cmd[cmd.index("--window-height") + 1], "892")
        self.assertIn("--stay-awake", cmd)
        self.assertIn("--no-audio", cmd)
        self.assertIn("--no-control", cmd)



if __name__ == "__main__":
    unittest.main()



