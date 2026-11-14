"""Tests for the AgentRedroid (agentdroid) CLI, compound pipeline, and general-purpose helpers."""

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


if __name__ == "__main__":
    unittest.main()
