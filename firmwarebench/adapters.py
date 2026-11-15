"""Standalone framework adapters. Both call the same narrowly scoped tools."""
import argparse
import json
import os
import uuid
from pathlib import Path
from urllib.request import Request, urlopen


def run(agent, endpoint, prompt, turns, logdir):
    def call(tool_name, **arguments):
        request = Request(endpoint + "/tools", json.dumps({"name": tool_name, "arguments": arguments}).encode(),
                          {"Content-Type": "application/json"})
        with urlopen(request, timeout=100) as response:
            return json.load(response)["result"]

    def read_source() -> str:
        """Read the current firmware.c and its immutable header."""
        return call("read_source")

    def replace_text(old: str, new: str) -> str:
        """Replace exactly one matching substring in firmware.c.

        Args:
            old: Exact existing text including whitespace.
            new: Replacement C source text. Use an empty string to delete.
        """
        return call("replace_text", old=old, new=new)

    def edit_line(line: int, code: str, expected: str) -> str:
        """Replace one numbered source line with zero or more C lines.

        Args:
            line: One-based line number in the current firmware.c.
            code: Replacement C code, or an empty string to delete the line.
            expected: Exact current content of that line, including indentation, without its newline.
        """
        return call("edit_line", line=line, code=code, expected=expected)

    def run_public_tests() -> str:
        """Compile the current source and run the public examples."""
        return call("run_public_tests")

    functions = [read_source, edit_line, replace_text, run_public_tests]
    if agent == "inspect":
        from inspect_ai import Task, eval
        from inspect_ai.agent import react
        from inspect_ai.dataset import Sample
        from inspect_ai.model import GenerateConfig, get_model
        from inspect_ai.tool import ToolDef
        import asyncio

        def wrap(func):
            from functools import wraps
            @wraps(func)
            async def execute(*args, **kwargs):
                return await asyncio.to_thread(func, *args, **kwargs)
            return ToolDef(execute, parallel=False)

        model = get_model("openai-api/bench/pilot", base_url=endpoint + "/v1", api_key="local",
                          responses_api=False, stream=False, strict_tools=False,
                          config=GenerateConfig(max_retries=0, max_tokens=768, temperature=0))
        task = Task(dataset=[Sample(input=prompt)], solver=react(tools=[wrap(f) for f in functions]))
        result = eval(task, model=model, display="none", log_dir=logdir, log_samples=False,
                      score=False)[0]
        if result.status == "error":
            raise RuntimeError(result.error.message if result.error else "Inspect evaluation error")
    else:
        from smolagents import OpenAIServerModel, ToolCallingAgent, tool
        model = OpenAIServerModel(model_id="pilot", api_base=endpoint + "/v1", api_key="local",
                                  client_kwargs={"max_retries": 0}, max_tokens=768, temperature=0)
        class MeasuredToolCallingAgent(ToolCallingAgent):
            def execute_tool_call(self, tool_name, arguments):
                if tool_name != "final_answer":
                    return super().execute_tool_call(tool_name, arguments)
                status = "failed"
                try:
                    result = super().execute_tool_call(tool_name, arguments)
                    status = "ok"
                    return result
                finally:
                    # Observe the native parser/executor, including JSON-text calls.
                    # Do not synthesize tool calls or alter their arguments/results.
                    payload = {"id": uuid.uuid4().hex, "name": tool_name, "status": status}
                    request = Request(endpoint + "/framework-calls", json.dumps(payload).encode(),
                                      {"Content-Type": "application/json"})
                    with urlopen(request, timeout=10) as response:
                        response.read()

        agent_loop = MeasuredToolCallingAgent(tools=[tool(f) for f in functions], model=model,
                                      max_steps=turns, max_tool_threads=1, verbosity_level=-1)
        agent_loop.run(prompt)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("agent", choices=["inspect", "smolagents"])
    parser.add_argument("endpoint")
    parser.add_argument("prompt_file", type=Path)
    parser.add_argument("turns", type=int)
    args = parser.parse_args()
    run(args.agent, args.endpoint, args.prompt_file.read_text(encoding="utf-8"), args.turns,
        str(args.prompt_file.parent / "inspect-logs"))



