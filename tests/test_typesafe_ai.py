"""Unit tests for TypeSafe AI integration."""

import unittest
from unittest.mock import MagicMock, patch
from agentdroid.typesafe_ai import TypeSafeAIClient


class TestTypeSafeAIClient(unittest.TestCase):
    def test_missing_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(ValueError):
                TypeSafeAIClient(api_key=None)

    def test_initialization_with_key(self):
        client = TypeSafeAIClient(api_key="test_key_123")
        self.assertEqual(client.api_key, "test_key_123")
        self.assertEqual(client.base_url, "https://api.typesafe.ai/v1")

    @patch("urllib.request.urlopen")
    def test_list_models_mock(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"models": [{"name": "jev-latest"}]}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = TypeSafeAIClient(api_key="mock_key")
        models = client.list_models()
        self.assertEqual(len(models), 1)
        self.assertEqual(models[0]["name"], "jev-latest")

    @patch("urllib.request.urlopen")
    def test_decide_mock(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = b'{"model": "jev-1.14.0", "answers": {"test": {"type": "choice", "choice": "tap_1", "confidence": 0.95}}}'
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = TypeSafeAIClient(api_key="mock_key")
        res = client.decide("state text", {"test": {"type": "choice"}})
        self.assertEqual(res["answers"]["test"]["choice"], "tap_1")
        self.assertIn("latency_ms", res)


if __name__ == "__main__":
    unittest.main()
