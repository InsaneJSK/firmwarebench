"""Per-trial loopback bridge for shared tools, model budgets and gateway evidence."""
import json
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .common import GATEWAY, ROOT, TASKS
from .grader import InfrastructureError, grade

# The bundled single worker shares this interval across consecutive Groq trials.
_groq_clock = threading.Lock()
_next_groq_call = 0.0


def pace_groq():
    global _next_groq_call
    with _groq_clock:
        now = time.monotonic()
        delay = max(0.0, _next_groq_call - now)
        _next_groq_call = now + delay + 30.0
    if delay:
        time.sleep(delay)
    return delay


def numbered(source):
    return "\n".join(f"{i}: {line}" for i, line in enumerate(source.splitlines(), 1))


def refresh_source(messages, source):
    """Refresh the task's mutable snapshot without rewriting observations or history."""
    opening, closing = "<firmware_source>", "</firmware_source>"
    refreshed = 0

    def update(text):
        nonlocal refreshed
        if opening not in text or closing not in text:
            return text
        before, _, rest = text.partition(opening)
        _, _, after = rest.partition(closing)
        refreshed += 1
        return before + opening + "\n" + numbered(source) + "\n" + closing + after

    for message in messages:
        if message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = update(content)
        elif isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    part["text"] = update(part["text"])
    return refreshed


def gateway(path, body=None, headers=None, timeout=90):
    auth = os.environ.get("BIFROST_API_KEY")
    headers = {"Content-Type": "application/json", **(headers or {})}
    if auth:
        headers["Authorization"] = "Bearer " + auth
    req = Request(GATEWAY + path, json.dumps(body).encode() if body is not None else None, headers)
    with urlopen(req, timeout=timeout) as res:
        return json.load(res)


class TrialBridge:
    def __init__(self, trial, config, workspace, emit):
        self.trial, self.config, self.workspace, self.emit = trial, config, workspace, emit
        self.turns = self.tools = 0
        self.request_ids = set()
        self.last_response_request_id = None
        self.framework_call_ids = set()
        self.next_step = "repair"
        self.lock = threading.RLock()
        self.triggered = False
        self.infrastructure_error = None
        self.limit_hit = False
        self.closed = False
        self.token = secrets.token_urlsafe(25)
        bridge = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    size = int(self.headers.get("Content-Length", 0))
                    if size > 262144 or size <= 0:
                        return self.reply(413, {"error": {"message": "Invalid request size"}})
                    body = json.loads(self.rfile.read(size))
                    with bridge.lock:
                        if bridge.closed:
                            return self.reply(410, {"error": {"message": "Trial finished"}})
                        if self.path == "/" + bridge.token + "/tools":
                            return self.reply(200, {"result": bridge.tool(body)})
                        if self.path == "/" + bridge.token + "/framework-calls":
                            return self.reply(*bridge.framework_call(body))
                        if self.path == "/" + bridge.token + "/v1/chat/completions":
                            return self.reply(*bridge.model(body))
                    self.reply(404, {"error": {"message": "Unknown endpoint"}})
                except Exception as exc:
                    bridge.infrastructure_error = str(exc)[:500]
                    self.reply(500, {"error": {"message": str(exc)[:500]}})

            def reply(self, code, payload):
                raw = json.dumps(payload).encode()
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                except (ConnectionError, OSError):
                    pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/{self.token}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.closed = True
        self.server.shutdown()
        self.server.server_close()
        with self.lock:
            pass

    def tool(self, body):
        name, args = body.get("name"), body.get("arguments", {})
        path = self.workspace / "firmware.c"
        source = path.read_text(encoding="utf-8")
        self.tools += 1
        status = "ok"
        if self.tools > self.config["tool_limit"]:
            status, output = "denied", "Tool budget exhausted."
        elif name == "read_source":
            header = (ROOT / "tasks" / self.trial["task"] / "firmware.h").read_text()
            output = "// firmware.h\n" + header + "\n// firmware.c\n" + numbered(source)
        elif name == "edit_line":
            lines = source.splitlines(keepends=True)
            index, code = args.get("line"), args.get("code")
            if type(index) is not int or not 1 <= index <= len(lines) or not isinstance(code, str):
                status, output = "failed", "Use a valid one-based line number and a string."
            elif "expected" in args and args["expected"] != lines[index-1].rstrip("\r\n"):
                status, output = "failed", "Source line changed. Read the current source and match its exact contents."
            elif len(source) + len(code) > 24576:
                status, output = "denied", "Source size limit exceeded."
            else:
                lines[index-1] = code.rstrip("\n") + "\n" if code else ""
                path.write_text("".join(lines), encoding="utf-8")
                output = "Updated firmware.c."
        elif name == "replace_text":
            old, new = args.get("old"), args.get("new")
            if not isinstance(old, str) or not isinstance(new, str) or not old or source.count(old) != 1:
                matches = source.count(old) if isinstance(old, str) and old else 0
                status, output = "failed", (f"Replacement rejected: found {matches} matches; exactly one is required. "
                                            "Use edit_line with the current line number and exact expected content.")
            elif len(source) - len(old) + len(new) > 24576:
                status, output = "denied", "Source size limit exceeded."
            else:
                path.write_text(source.replace(old, new, 1), encoding="utf-8")
                output = "Updated firmware.c."
        elif name == "run_public_tests":
            if self.trial["scenario"] == "broken-tool" and not self.triggered:
                self.triggered = True
                self.emit("fault", {"profile": "broken-tool", "evidence": "First public-test call returned a transient error"})
                status, output = "failed", "Transient test service error. Retry the same tool."
            else:
                try:
                    result = grade(self.trial["task"], source, reserved=False)
                    output = json.dumps(result)
                    if not result["pass"]:
                        status = "failed"
                except InfrastructureError as exc:
                    self.infrastructure_error = str(exc)
                    status, output = "failed", "Public-test infrastructure failed: " + str(exc)
        else:
            status, output = "denied", "Unknown tool."
        if self.config.get("show_edit_feedback") and name in ("edit_line", "replace_text"):
            output += "\n" + numbered(path.read_text(encoding="utf-8"))
        if status == "ok" and name in ("edit_line", "replace_text"):
            self.next_step = "test"
        elif name == "run_public_tests":
            if output == "Transient test service error. Retry the same tool.":
                self.next_step = "retry_test"
            else:
                self.next_step = "submit" if status == "ok" else "repair"
        self.emit("tool", {"name": name, "status": status, "arguments": args, "output": output})
        return output

    def framework_call(self, body):
        """Record a native completion attempt without spending a shared-tool budget."""
        call_id = body.get("id")
        if (self.trial.get("agent") != "smolagents" or body.get("name") != "final_answer"
                or body.get("status") not in ("ok", "failed")
                or not isinstance(call_id, str) or not 1 <= len(call_id) <= 128
                or self.last_response_request_id is None):
            return 400, {"error": "Invalid framework completion event"}
        if call_id not in self.framework_call_ids:
            self.framework_call_ids.add(call_id)
            self.emit("framework_call", {"id": call_id, "agent": "smolagents", "name": "final_answer",
                "status": body["status"], "request_id": self.last_response_request_id,
                "basis": "native-execution-v1"})
        return 200, {"recorded": True}

    def model(self, body):
        if self.turns >= self.config["turn_limit"]:
            self.limit_hit = True
            return 400, {"error": {"message": "Trial decision-turn limit reached", "type": "budget"}}
        self.turns += 1
        request_id = str(uuid.uuid4())
        self.request_ids.add(request_id)
        route = self.config["route"]
        outage = self.trial["scenario"] == "model-outage" and self.turns == 1
        requested = "offline/" + route.split("/", 1)[-1] if outage else route
        body["model"] = requested
        body["stream"] = False
        body.pop("stream_options", None)
        if outage:
            body["fallbacks"] = [route]
        decision = {"turn": self.turns, "request_id": request_id, "requested": requested}
        if route == "groq/openai/gpt-oss-20b" and body.get("tools"):
            finish = "submit" if self.trial.get("agent") == "inspect" else "final_answer"
            instructions = {
                "repair": "Use the current source and public-test observations to make a repair. Prefer edit_line with its exact expected content. A rejected edit did not change the file.",
                "test": "The edit is already applied. Call run_public_tests with {} to check the current source.",
                "retry_test": "The test service returned a transient error. Retry run_public_tests with {} on the current source.",
                "submit": f"Public tests passed for the current source. Complete the task by calling {finish} with your repair summary in answer.",
            }
            instruction = instructions[self.next_step] + " Use a native function call for your action."
            refreshed = 0
            if self.config.get("show_edit_feedback"):
                source = (self.workspace / "firmware.c").read_text(encoding="utf-8")
                refreshed = refresh_source(body["messages"], source)
                instruction += "\nCurrent firmware.c\n" + numbered(source)
            body["messages"].append({"role": "user", "content": instruction})
            body["tool_choice"] = "auto"
            body["parallel_tool_calls"] = False
            decision.update(tool_choice="auto", next_step=self.next_step, completion_tool=finish, refreshed_snapshots=refreshed)
        self.emit("decision", decision)
        if route == "groq/openai/gpt-oss-20b":
            body["reasoning_effort"] = "low"
            waited = pace_groq()
            if waited:
                self.emit("pacing", {"request_id": request_id, "seconds": round(waited, 3)})
        try:
            res = gateway("/v1/chat/completions", body,
                          {"x-bf-lh-trial": self.trial["id"], "x-bf-lh-call": request_id},
                          timeout=self.config["seconds"])
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            code = getattr(exc, "code", 502)
            detail = exc.read(600).decode(errors="replace") if isinstance(exc, HTTPError) else str(exc)
            self.emit("model_error", {"request_id": request_id, "status": code, "detail": detail})
            self.infrastructure_error = f"Gateway returned {code}. {detail}"
            return code, {"error": {"message": detail}}
        extra = res.get("extra_fields", {})
        if route == "groq/openai/gpt-oss-20b":
            # The pinned Inspect client stringifies structured reasoning on replay.
            # Return the public answer and tool calls without provider-only reasoning.
            for choice in res["choices"]:
                for field in ("reasoning_details", "reasoning_content", "reasoning"):
                    choice["message"].pop(field, None)
        self.last_response_request_id = request_id
        self.emit("response", {"request_id": request_id, "provider": extra.get("provider"),
            "model": res.get("model"), "usage": res.get("usage"), "response_id": res.get("id"),
            "tools_requested": [tc["function"]["name"] for tc in res["choices"][0]["message"].get("tool_calls") or []]})
        return 200, res

    def reconcile(self):
        if not self.request_ids:
            return
        attempts = {}
        for delay in [0, 0.3, 0.8, 1.5, 2]:
            time.sleep(delay)
            try:
                logs = gateway("/api/logs?limit=250", timeout=5)["logs"]
            except (OSError, ValueError, KeyError):
                continue
            for row in logs:
                metadata = row.get("metadata") or {}
                rid = metadata.get("call")
                if rid not in self.request_ids or metadata.get("trial") != self.trial["id"]:
                    continue
                error = row.get("error_details") or {}
                attempts[row["id"]] = {"id": row["id"], "request_id": rid, "parent": row.get("parent_request_id"),
                    "provider": row.get("provider"), "model": row.get("model"), "status": row.get("status"),
                    "fallback": row.get("fallback_index", 0), "retries": row.get("number_of_retries", 0),
                    "usage": row.get("token_usage"), "cost": row.get("cost"), "http_status": error.get("status_code"),
                    "timestamp": row.get("timestamp")}
            known = {row["request_id"] for row in attempts.values() if row["status"] == "success"}
            if known == self.request_ids and (self.trial["scenario"] != "model-outage" or
                                               any(row["provider"] == "offline" for row in attempts.values())):
                break
        for row in sorted(attempts.values(), key=lambda r: (r["timestamp"], r["fallback"])):
            self.emit("gateway", row)
            if row["provider"] == "offline" and row["http_status"] == 503:
                self.triggered = True
                self.emit("fault", {"profile": "model-outage", "request_id": row["request_id"],
                                    "evidence": "Controlled primary returned HTTP 503"})

