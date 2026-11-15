"""Tests for the AgentDroid (agentdroid) CLI, compound pipeline, and general-purpose helpers."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from agentdroid.adb import AdbDevice, CrashReport, InstalledAppInfo
from agentdroid.artemis_bridge import ArtemisBridge, GoalExecutionResult
from agentdroid.cli import build_parser, main, normalize_argv
from agentdroid.pipeline import CompoundPipeline, PipelineSpec


class TestCliNormalizationAndParsing(unittest.TestCase):
    def test_normalize_shorthand_to_run(self) -> None:
        argv = ["agentdroid", "--headless", "-i", "fdroid:markor", "Open Markor and create a note"]
        normalized = normalize_argv(argv)
        self.assertEqual(normalized[1], "run")
        self.assertIn("--headless", normalized)

    def test_known_subcommands_preserved(self) -> None:
        for sub in ("run", "watch", "up", "down", "provision", "app", "device", "ui", "pipeline", "doctor", "serve"):
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
                "--step",
                "Read top 3 stories",
                "--step",
                "Summarize points",
                "--expect",
                "JSON list of stories",
                "--until-output",
                "--max-attempts",
                "3",
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
        self.assertEqual(args.goals_opt, ["Read top 3 stories", "Summarize points"])
        self.assertEqual(args.expect, "JSON list of stories")
        self.assertTrue(args.until_output)
        self.assertEqual(args.max_attempts, 3)
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
            goals=["Step 1: Read file", "Step 2: Summarize content"],
            combine_goals=True,
            expected_output="summary string",
            until_output=True,
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
        pipeline.artemis.execute_goal = MagicMock(
            return_value=GoalExecutionResult(
                succeeded=True,
                status="completed",
                goal="combined",
                profile="flash",
                session_id="sess-123",
                output={"summary": "Hello from Android"},
                attempts=1,
                steps_count=4,
                duration_sec=3.5,
            )
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
        self.assertEqual(report["agent_output"], {"summary": "Hello from Android"})
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

    def test_until_output_retries_with_screen_recovery_context(self) -> None:
        bridge = ArtemisBridge(base_url="http://127.0.0.1:8000", device_serial="127.0.0.1:5555")
        call_goals: list[str] = []

        def fake_single(goal: str, **kwargs):
            call_goals.append(goal)
            if len(call_goals) == 1:
                return GoalExecutionResult(
                    succeeded=False,
                    status="failed",
                    goal=goal,
                    profile="flash",
                    session_id="s1",
                    error="Popup blocked button",
                )
            return GoalExecutionResult(
                succeeded=True,
                status="completed",
                goal=goal,
                profile="flash",
                session_id="s2",
                output={"done": True},
            )

        bridge._execute_single_attempt = fake_single  # type: ignore[method-assign]
        res = bridge.execute_goal(
            "Complete task and extract result",
            expected_output="JSON with done=true",
            until_output=True,
            max_attempts=3,
            ui_context_provider=lambda: {
                "foreground": {"component": "com.app/.MainActivity"},
                "elements": [{"label": "Dismiss Popup"}, {"label": "Continue"}],
            },
        )
        self.assertTrue(res.succeeded)
        self.assertEqual(res.attempts, 2)
        self.assertIn("Recovery Attempt 2/3", call_goals[1])
        self.assertIn("Dismiss Popup", call_goals[1])


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


class TestAgentDroidCloudServer(unittest.TestCase):
    def test_pipeline_spec_from_dict_shorthands(self) -> None:
        raw_dict = {
            "open_url": "https://example.com",
            "install": "fdroid:net.gsantner.markor",
            "launch": "auto",
            "do": ["scroll:down", "click:About"],
            "assert_text": "About",
            "notifications": True,
            "clipboard": "cloud-test-text",
        }
        spec = PipelineSpec.from_dict(raw_dict)
        self.assertEqual(spec.open_urls, ["https://example.com"])
        self.assertEqual(spec.install_apks, ["fdroid:net.gsantner.markor"])
        self.assertEqual(spec.launch_target, "auto")
        self.assertEqual(len(spec.ui_actions), 2)
        self.assertEqual(spec.ui_actions[0], {"type": "scroll", "direction": "down"})
        self.assertEqual(spec.ui_actions[1], {"type": "click", "selector": "About"})
        self.assertEqual(spec.assert_texts, ["About"])
        self.assertTrue(spec.read_notifications)
        self.assertEqual(spec.set_clipboard, "cloud-test-text")

    def test_server_http_endpoints_and_auth(self) -> None:
        import threading
        import urllib.request
        from agentdroid.server import AgentDroidServer

        # Start server with an ephemeral port (port 0) and API Key
        server = AgentDroidServer(host="127.0.0.1", port=0, api_key="secret-123")
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()

        base_url = f"http://127.0.0.1:{port}"

        try:
            # 1. GET /health (Public endpoint, CORS headers)
            req = urllib.request.Request(f"{base_url}/health")
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get("Access-Control-Allow-Origin"), "*")
                data = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(data.get("ok"))
                self.assertEqual(data.get("service"), "agentdroid")

            # 2. GET /playground (Public web developer dashboard)
            with urllib.request.urlopen(f"{base_url}/playground", timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                body = resp.read().decode("utf-8")
                self.assertIn("AgentDroid", body)
                self.assertIn("Live Device Control", body)

            # 3. GET /api/v1/ui/dump WITHOUT auth -> 401 Unauthorized
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"{base_url}/api/v1/ui/dump", timeout=5.0)
            self.assertEqual(ctx.exception.code, 401)

            # 4. Mock helper and test GET /api/v1/ui/dump WITH X-API-Key
            server._helper.dump_compact_ui = MagicMock(
                return_value={
                    "ok": True,
                    "element_count": 2,
                    "elements": [
                        {"id": 1, "label": "Settings", "class": "android.widget.TextView", "center": [100, 200]},
                        {"id": 2, "label": "Search", "class": "android.widget.Button", "center": [300, 400]},
                    ],
                }
            )
            req_auth = urllib.request.Request(
                f"{base_url}/api/v1/ui/dump",
                headers={"X-API-Key": "secret-123"},
            )
            with urllib.request.urlopen(req_auth, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                dump = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(dump["element_count"], 2)
                self.assertEqual(dump["elements"][0]["label"], "Settings")

            # 5. POST /api/v1/do WITH Authorization: Bearer <key>
            server._helper.tap_element = MagicMock(return_value={"success": True, "selector": "Settings"})
            post_req = urllib.request.Request(
                f"{base_url}/api/v1/do",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": "Bearer secret-123",
                },
                data=json.dumps({"action": "click:Settings"}).encode("utf-8"),
                method="POST",
            )
            with urllib.request.urlopen(post_req, timeout=5.0) as resp:
                self.assertEqual(resp.status, 200)
                result = json.loads(resp.read().decode("utf-8"))
                self.assertTrue(result.get("ok"))
                self.assertEqual(len(result["steps"]), 1)
                self.assertTrue(result["steps"][0]["success"])

            # 6. POST /api/v1/run compound pipeline endpoint
            with patch("agentdroid.server.CompoundPipeline") as mock_pipeline_cls:
                mock_pipeline_inst = MagicMock()
                mock_pipeline_inst.run.return_value = {
                    "ok": True,
                    "mode": "headless",
                    "opened_urls": [{"uri": "https://example.com"}],
                    "agent_runs": [],
                }
                mock_pipeline_cls.return_value = mock_pipeline_inst

                run_req = urllib.request.Request(
                    f"{base_url}/api/v1/run",
                    headers={
                        "Content-Type": "application/json",
                        "X-API-Key": "secret-123",
                    },
                    data=json.dumps({"open_url": "https://example.com"}).encode("utf-8"),
                    method="POST",
                )
                with urllib.request.urlopen(run_req, timeout=5.0) as resp:
                    self.assertEqual(resp.status, 200)
                    res_data = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(res_data.get("ok"))
                    self.assertEqual(res_data["opened_urls"][0]["uri"], "https://example.com")
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()


