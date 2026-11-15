import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from firmwarebench.bridge import TrialBridge


class GroqBridgeTests(unittest.TestCase):
    def test_edit_feedback_shows_current_line_numbers_only_when_enabled(self):
        with TemporaryDirectory() as workspace:
            path = Path(workspace, "firmware.c")
            bridge = TrialBridge({"id": "pilot"}, {"tool_limit": 8}, path.parent, Mock())
            self.addCleanup(bridge.stop)
            for enabled in (False, True):
                with self.subTest(enabled=enabled):
                    path.write_text("one\ntwo\nthree\n", encoding="utf-8")
                    bridge.config["show_edit_feedback"] = enabled
                    observation = bridge.tool({"name": "edit_line", "arguments": {"line": 2, "code": ""}})
                    self.assertEqual(path.read_text(encoding="utf-8"), "one\nthree\n")
                    expected = "Updated firmware.c."
                    if enabled:
                        expected += "\n1: one\n2: three"
                    self.assertEqual(observation, expected)

    @patch("firmwarebench.bridge.pace_groq", return_value=0)
    @patch("firmwarebench.bridge.gateway")
    def test_tool_call_survives_reasoning_response(self, gateway, pace):
        route = "groq/openai/gpt-oss-20b"
        trial = {"id": "pilot", "scenario": "model-outage"}
        config = {"route": route, "turn_limit": 4, "seconds": 300}
        bridge = TrialBridge(trial, config, None, Mock())
        self.addCleanup(bridge.stop)
        call = {"id": "one", "function": {"name": "read_source", "arguments": "{}"}}
        message = {"role": "assistant", "content": None, "tool_calls": [call],
                   "reasoning_details": [{"index": 0}], "reasoning_content": "private"}
        gateway.return_value = {"choices": [{"message": message}], "usage": {"total_tokens": 42}}
        code, response = bridge.model({"messages": [{"role": "user", "content": "Read the source."}]})
        sent = gateway.call_args.args[1]
        self.assertEqual((sent["model"], sent["fallbacks"], sent["reasoning_effort"]),
                         ("offline/openai/gpt-oss-20b", [route], "low"))
        self.assertEqual(code, 200)
        self.assertEqual(response["choices"][0]["message"],
                         {"role": "assistant", "content": None, "tool_calls": [call]})
        self.assertEqual(response["usage"], {"total_tokens": 42})
        pace.assert_called_once()
