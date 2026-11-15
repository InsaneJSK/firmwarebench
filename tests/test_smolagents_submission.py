import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from firmwarebench.adapters import run
from firmwarebench.metrics import metrics
from firmwarebench.bridge import TrialBridge, refresh_source


class SubmissionTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.workspace = Path(directory.name)
        (self.workspace / "firmware.c").write_text("before\nkeep\n", encoding="utf-8")
        self.emit = Mock()
        self.bridge = TrialBridge(
            {"id": "trial", "agent": "smolagents", "task": "uart", "scenario": "clean"},
            {"route": "groq/openai/gpt-oss-20b", "turn_limit": 6, "tool_limit": 8,
             "seconds": 300, "show_edit_feedback": True},
            self.workspace, self.emit,
        )
        self.addCleanup(self.bridge.stop)
        self.gateway = self.enterContext(patch("firmwarebench.bridge.gateway"))
        self.enterContext(patch("firmwarebench.bridge.pace_groq", return_value=0))
        self.gateway.return_value = {"choices": [{"message": {}}]}

    def decision(self, finish="final_answer"):
        tools = [{"type": "function", "function": {"name": name}}
                 for name in ("edit_line", "replace_text", "run_public_tests", finish)]
        self.bridge.model({"messages": [{"role": "user", "content": "Repair."}],
                           "tools": tools.copy(), "tool_choice": "required"})
        body = self.gateway.call_args.args[1]
        self.assertEqual(body["tools"], tools)
        self.assertEqual(body["tool_choice"], "auto")
        self.assertFalse(body["parallel_tool_calls"])
        return body["messages"][-1]["content"]

    def test_both_agents_receive_current_state_and_native_completion_guidance(self):
        for agent, finish in (("inspect", "submit"), ("smolagents", "final_answer")):
            with self.subTest(agent=agent):
                self.bridge.trial["agent"] = agent
                self.bridge.next_step = "repair"
                self.assertIn("Prefer edit_line", self.decision(finish))
                self.bridge.tool({"name": "edit_line", "arguments": {"line": 1, "code": "after"}})
                self.assertIn("already applied", self.decision(finish))
                with patch("firmwarebench.bridge.grade", return_value={"pass": True}):
                    self.bridge.tool({"name": "run_public_tests"})
                instruction = self.decision(finish)
                self.assertIn("calling " + finish, instruction)
                self.assertIn("1: after", instruction)

    def test_stale_line_edit_is_rejected_and_source_is_preserved(self):
        edit = {"name": "edit_line", "arguments": {"line": 1, "code": "", "expected": "before"}}
        self.bridge.tool(edit)
        output = self.bridge.tool(edit)
        self.assertEqual((self.workspace / "firmware.c").read_text(), "keep\n")
        self.assertIn("Source line changed", output)
        self.assertIn("1: keep", output)
        self.assertEqual(self.bridge.next_step, "test")
        statuses = [args[1]["status"] for args, _ in self.emit.call_args_list if args[0] == "tool"]
        self.assertEqual(statuses, ["ok", "failed"])

    def test_retry_then_completion_and_new_edit_invalidates_public_success(self):
        self.bridge.trial["scenario"] = "broken-tool"
        self.bridge.tool({"name": "run_public_tests"})
        self.assertIn("Retry run_public_tests", self.decision())
        with patch("firmwarebench.bridge.grade", return_value={"pass": True}):
            self.bridge.tool({"name": "run_public_tests"})
        self.assertIn("calling final_answer", self.decision())
        self.bridge.tool({"name": "replace_text", "arguments": {"old": "before", "new": "after"}})
        self.assertIn("already applied", self.decision())
        with patch("firmwarebench.bridge.grade", return_value={"pass": False}):
            self.bridge.tool({"name": "run_public_tests"})
        self.assertIn("make a repair", self.decision())

    def test_other_routes_keep_requested_tool_choice(self):
        self.bridge.config["route"] = "ollama/qwen2.5:3b"
        request = {"messages": [], "tools": [{"type": "function", "function": {"name": "read_source"}}],
                   "tool_choice": "required"}
        self.bridge.model(request)
        self.assertEqual(self.gateway.call_args.args[1]["tool_choice"], "required")
        self.assertEqual(self.gateway.call_args.args[1]["messages"], [])

    def test_refreshes_task_snapshot_in_both_wire_formats_only(self):
        content = "Issue stays\n<firmware_source>\nold\n</firmware_source>\nArchived note stays"
        messages = [{"role": "user", "content": content},
                    {"role": "user", "content": [{"type": "text", "text": content}]},
                    {"role": "assistant", "content": content},
                    {"role": "tool", "content": "historical result"}]
        self.assertEqual(refresh_source(messages, "new\nkeep\n"), 2)
        for text in (messages[0]["content"], messages[1]["content"][0]["text"]):
            self.assertEqual(text, content.replace("old", "1: new\n2: keep"))
        self.assertEqual(messages[2]["content"], content)
        self.assertEqual(messages[3]["content"], "historical result")

    def test_ambiguous_replacement_returns_actionable_feedback_without_mutation(self):
        source = "    reset();\n        reset();\n"
        (self.workspace / "firmware.c").write_text(source)
        output = self.bridge.tool({"name": "replace_text", "arguments": {"old": "    reset();", "new": ""}})
        self.assertIn("found 2 matches", output)
        self.assertIn("Use edit_line", output)
        self.assertEqual((self.workspace / "firmware.c").read_text(), source)
        self.bridge.tool({"name": "edit_line", "arguments": {"line": 1, "expected": "    reset();", "code": ""}})
        self.assertEqual((self.workspace / "firmware.c").read_text(), "        reset();\n")

    def test_smolagents_json_completion_executes_its_native_final_answer(self):
        from smolagents.default_tools import FinalAnswerTool
        content = json.dumps({"name": "final_answer", "arguments": {"answer": "Verified repair."}})
        self.gateway.return_value = {
            "id": "json-completion", "object": "chat.completion", "created": 1, "model": "pilot",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        with patch.object(FinalAnswerTool, "forward", autospec=True,
                          side_effect=lambda self, answer: answer) as finish:
            run("smolagents", self.bridge.endpoint, "Submit the verified repair.", 6, str(self.workspace))
        self.assertEqual(self.gateway.call_count, 1)
        self.assertEqual(finish.call_count, 1)
        self.assertEqual(finish.call_args.kwargs["answer"], "Verified repair.")
        events = [{"kind": args[0], "data": args[1]} for args, _ in self.emit.call_args_list]
        observed = [e["data"] for e in events if e["kind"] == "framework_call"]
        self.assertEqual(len(observed), 1)
        self.assertEqual(observed[0]["status"], "ok")
        self.assertEqual(observed[0]["request_id"], next(e["data"]["request_id"] for e in events if e["kind"] == "response"))
        values = metrics({"events": events})
        self.assertEqual((values["finish_calls"], values["tool_calls"], values["steps"]), (1, 1, 2))
        self.assertEqual(self.bridge.tools, 0)

    def test_rejected_json_completion_is_counted_as_a_native_attempt(self):
        content = json.dumps({"name": "final_answer", "arguments": {"wrong": "missing answer"}})
        self.gateway.return_value = {
            "id": "bad-completion", "object": "chat.completion", "created": 1, "model": "pilot",
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        self.bridge.config["turn_limit"] = 1
        run("smolagents", self.bridge.endpoint, "Submit.", 1, str(self.workspace))
        events = [{"kind": args[0], "data": args[1]} for args, _ in self.emit.call_args_list]
        observed = [e["data"] for e in events if e["kind"] == "framework_call"]
        self.assertEqual([e["status"] for e in observed], ["failed"])
        self.assertEqual(metrics({"events": events})["finish_calls"], 1)

    def test_framework_event_validation_and_duplicate_delivery(self):
        body = {"id": "completion", "name": "final_answer", "status": "ok"}
        self.assertEqual(self.bridge.framework_call(body)[0], 400)
        self.decision()
        self.assertEqual(self.bridge.framework_call({**body, "name": "edit_line"})[0], 400)
        self.assertEqual(self.bridge.framework_call(body)[0], 200)
        self.assertEqual(self.bridge.framework_call(body)[0], 200)
        observed = [args[1] for args, _ in self.emit.call_args_list if args[0] == "framework_call"]
        self.assertEqual(len(observed), 1)
        self.assertEqual(self.bridge.tools, 0)

    def test_real_frameworks_edit_retry_and_submit(self):
        for agent, finish in (("inspect", "submit"), ("smolagents", "final_answer")):
            with self.subTest(agent=agent):
                self.emit.reset_mock()
                self.bridge.trial.update(agent=agent, scenario="broken-tool")
                self.bridge.turns = self.bridge.tools = 0
                self.bridge.triggered = False
                self.bridge.next_step = "repair"
                (self.workspace / "firmware.c").write_text("before\nkeep\n")
                actions = [("edit_line", {"line": 1, "expected": "before", "code": "after"}),
                           ("run_public_tests", {}), ("run_public_tests", {}),
                           (finish, {"answer": "Repair applied and verified."})]
                calls = []

                def respond(path, body, headers, timeout):
                    calls.append(body)
                    name, arguments = actions[len(calls) - 1]
                    available = {t["function"]["name"]: t["function"] for t in body["tools"]}
                    self.assertIn("expected", available["edit_line"]["parameters"]["required"])
                    self.assertIn(name, available)
                    return {"id": "reply-" + str(len(calls)), "object": "chat.completion", "created": 1,
                            "model": "pilot", "choices": [{"index": 0, "finish_reason": "tool_calls",
                            "message": {"role": "assistant", "content": None, "tool_calls": [{
                                "id": "call-" + str(len(calls)), "type": "function",
                                "function": {"name": name, "arguments": json.dumps(arguments)}}]}}],
                            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}}

                self.gateway.side_effect = respond
                with patch("firmwarebench.bridge.grade", return_value={"pass": True}):
                    run(agent, self.bridge.endpoint, "Repair and run public tests, then submit.", 6,
                        str(self.workspace / (agent + "-logs")))
                self.assertEqual(len(calls), 4)
                self.assertTrue(self.bridge.triggered)
                self.assertEqual((self.workspace / "firmware.c").read_text(), "after\nkeep\n")
                self.assertFalse(self.bridge.infrastructure_error)
                events = [{"kind": args[0], "data": args[1]} for args, _ in self.emit.call_args_list]
                values = metrics({"events": events})
                self.assertEqual((values["finish_calls"], values["tool_calls"], values["steps"]), (1, 4, 8))
