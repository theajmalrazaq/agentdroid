"""Unit tests for TypeSafe AI integration."""

import unittest
from unittest.mock import MagicMock, patch
from agentdroid.typesafe_ai import TypeSafeAIClient, extract_text_inputs


class TestTypeSafeAIClient(unittest.TestCase):
    def test_missing_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                TypeSafeAIClient(api_key=None)

    def test_initialization_with_key(self):
        client = TypeSafeAIClient(api_key="test_key_123")
        self.assertEqual(client.api_key, "test_key_123")
        self.assertEqual(client.base_url, "https://api.typesafe.ai/v1")

    def test_extract_text_inputs(self):
        self.assertEqual(
            extract_text_inputs("Create contact 'Ada' with phone '5550199' and save"),
            ["Ada", "5550199"],
        )

    @patch("http.client.HTTPSConnection")
    def test_list_models_mock(self, mock_https):
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"models": [{"name": "jev-latest"}]}'
        mock_conn.getresponse.return_value = mock_resp
        mock_https.return_value = mock_conn

        client = TypeSafeAIClient(api_key="mock_key")
        models = client.list_models()
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["name"], "jev-latest")

    @patch("http.client.HTTPSConnection")
    def test_decide_and_rank_mock(self, mock_https):
        mock_conn = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = (
            b'{"model": "jev-1.14.0", "answers": {"selected_action": {"choice": "fill_2_0", "confidence": 0.95}, '
            b'"is_goal_met": {"noul": 0.1}}}'
        )
        mock_conn.getresponse.return_value = mock_resp
        mock_https.return_value = mock_conn

        client = TypeSafeAIClient(api_key="mock_key")
        ui = {
            "foreground": {"package": "net.gsantner.markor", "activity": "MainActivity"},
            "elements": [
                {"id": 1, "class": "TextView", "label": "Name", "center": [540, 326]},
                {"id": 2, "class": "EditText", "label": "EditText", "editable": True, "center": [540, 390]},
            ],
        }
        res = client.rank_next_action(ui, "Create note 'bench_log'")
        self.assertEqual(res["action_key"], "fill_2_0")
        self.assertEqual(res["action_type"], "fill")
        self.assertEqual(res["fill_text"], "bench_log")
        self.assertFalse(res["is_goal_met"])
        self.assertIn("latency_ms", res)


if __name__ == "__main__":
    unittest.main()
