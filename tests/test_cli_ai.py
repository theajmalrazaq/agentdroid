"""Unit tests for 'agentdroid ai' CLI subcommand."""

import argparse
import unittest
from unittest.mock import MagicMock, patch

from agentdroid.cli import build_parser, cmd_ai, normalize_argv


class TestCliAiSubcommand(unittest.TestCase):
    def test_normalize_argv_preserves_ai_subcommand(self):
        argv = ["agentdroid", "ai", "Start stopwatch", "-w"]
        norm = normalize_argv(argv)
        self.assertEqual(norm, ["agentdroid", "ai", "Start stopwatch", "-w"])

    def test_parse_ai_arguments(self):
        parser = build_parser()
        args = parser.parse_args([
            "ai",
            "Open Clock and tap Stopwatch",
            "-s", "127.0.0.1:5555",
            "-w",
            "--max-steps", "5",
            "--launch", "com.google.android.deskclock",
            "--model", "jev-latest",
            "-j",
        ])
        self.assertEqual(args.subcommand, "ai")
        self.assertEqual(args.prompt, "Open Clock and tap Stopwatch")
        self.assertEqual(args.serial, "127.0.0.1:5555")
        self.assertTrue(args.watch)
        self.assertEqual(args.max_steps, 5)
        self.assertEqual(args.launch, "com.google.android.deskclock")
        self.assertEqual(args.model, "jev-latest")
        self.assertTrue(args.json)

    @patch("agentdroid.adb.AdbDevice.connect", return_value=True)
    @patch("agentdroid.engine.AndroidEngine.get_screen_data")
    @patch("agentdroid.typesafe_ai.TypeSafeAIClient.rank_next_action")
    def test_cmd_ai_execution_loop(self, mock_rank, mock_get_screen, mock_connect):
        mock_get_screen.return_value = {
            "foreground": {"component": "com.google.android.deskclock/.DeskClock"},
            "elements": [{"id": 1, "label": "Stopwatch", "center": [540, 300]}],
        }
        mock_rank.return_value = {
            "action_key": "tap_1",
            "confidence": 0.98,
            "latency_ms": 120.0,
            "is_goal_met": True,
            "matched_element": {"id": 1, "label": "Stopwatch", "center": [540, 300]},
        }

        parser = build_parser()
        args = parser.parse_args(["ai", "Switch to stopwatch", "--key", "test-typesafe-key", "--max-steps", "2", "-j"])

        with patch("agentdroid.engine.AndroidEngine.tap") as mock_tap:
            mock_tap.return_value = {"success": True}
            ret = cmd_ai(args)
            self.assertEqual(ret, 0)
            mock_tap.assert_called_once_with(540.0, 300.0)

    @patch.dict("os.environ", {"TYPESAFE_API_KEY": ""}, clear=False)
    @patch("agentdroid.adb.AdbDevice.connect", return_value=True)
    def test_cmd_ai_requires_api_key(self, mock_connect):
        parser = build_parser()
        args = parser.parse_args(["ai", "Switch to stopwatch", "--max-steps", "1", "-j"])
        with self.assertRaises(ValueError):
            cmd_ai(args)

    @patch("agentdroid.adb.AdbDevice.connect", return_value=True)
    @patch("agentdroid.adb.AdbDevice.trim_background_apps", return_value=["com.pkg.one", "com.pkg.two"])
    def test_cmd_device_clean(self, mock_trim, mock_connect):
        from agentdroid.cli import cmd_device

        parser = build_parser()
        args = parser.parse_args(["device", "clean", "-j"])
        ret = cmd_device(args)
        self.assertEqual(ret, 0)
        mock_trim.assert_called_once()


if __name__ == "__main__":
    unittest.main()
