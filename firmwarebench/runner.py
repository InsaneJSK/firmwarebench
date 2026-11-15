"""Single-worker trial execution. Only the host-owned tool bridge touches the candidate."""
import difflib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from .bridge import TrialBridge, numbered
from .common import ROOT, task_spec, versions
from .grader import grade


def execute(trial, config, publish=lambda event: None):
    started = time.time()
    events = []
    event_lock = threading.Lock()

    def emit(kind, data):
        event = {"kind": kind, "at": round(time.time() - started, 3), "data": data}
        with event_lock:
            events.append(event)
            publish(event)

    task = trial["task"]
    spec = task_spec(task, config["suite"])
    starter = (ROOT / "tasks" / task / "firmware.c").read_text(encoding="utf-8")
    result = {"versions": versions(task, config["route"], config["suite"]), "events": events, "source": starter, "diff": "",
              "agent_seconds": 0, "grader_seconds": 0, "queue_seconds": max(0, started-trial["queued"]),
              "triggered": False, "verifier": None, "status": "invalid", "reason": ""}
    with tempfile.TemporaryDirectory(prefix="firmwarebench-") as temp:
        workspace = Path(temp)
        candidate = workspace / "firmware.c"
        candidate.write_text(starter, encoding="utf-8")
        prompt = ("Repair firmware.c. The issue specification is authoritative. Prefer edit_line for the smallest "
                  "source change, copying the current line into expected including indentation. "
                  "Use run_public_tests to verify the edited source. Retry transient test errors. "
                  "After successful tests, submit through your native completion tool.\n\nIssue: "
                  + spec["issue"] + "\n\nfirmware.h\n" + (ROOT/"tasks"/task/"firmware.h").read_text()
                  + "\nCurrent numbered firmware.c (numbers are not part of the file)\n<firmware_source>\n"
                  + numbered(starter) + "\n</firmware_source>")
        if config.get("show_edit_feedback"):
            prompt += ("\n\nEditor tools return the updated numbered source after every edit attempt. "
                       "Use that copy for subsequent line numbers. An empty code string deletes the line "
                       "and shifts later lines up. Call run_public_tests with an empty JSON object {}.")
        if "diagnostic" in spec:
            prompt += "\n\nPublic diagnostic trace: " + spec["diagnostic"]
        if trial["scenario"] == "misleading-fixture":
            prompt += "\n\nArchived fixture note: " + spec["obsolete"]
            emit("fault", {"profile": "misleading-fixture", "evidence": spec["obsolete"]})
        prompt_path = workspace / "issue.txt"
        prompt_path.write_text(prompt, encoding="utf-8")
        bridge = TrialBridge(trial, config, workspace, emit)
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR", "HOME", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "LANG", "COMSPEC", "NUMBER_OF_PROCESSORS", "PATHEXT"}}
        env.update(PYTHONPATH=str(ROOT), PYTHONUTF8="1", HF_HUB_OFFLINE="1", INSPECT_NO_LOG_TIMESTAMPS="1")
        before = time.monotonic()
        try:
            with (workspace / "agent.log").open("wb") as log:
                proc = subprocess.run([sys.executable, "-m", "firmwarebench.adapters", trial["agent"],
                                       bridge.endpoint, str(prompt_path), str(config["turn_limit"])],
                                      cwd=workspace, env=env, stdout=log, stderr=log,
                                      timeout=config["seconds"])
            if proc.returncode:
                tail = (workspace/"agent.log").read_text(encoding="utf-8", errors="replace").splitlines()
                result["reason"] = "Decision-turn limit reached." if bridge.limit_hit else (tail[-1][:480] if tail else "Adapter exited.")
                if bridge.turns == 0:
                    bridge.infrastructure_error = result["reason"]
                if not bridge.limit_hit:
                    emit("adapter_exit", {"code": proc.returncode, "detail": result["reason"]})
        except subprocess.TimeoutExpired:
            result["reason"] = "Agent time limit reached."
            emit("limit", {"seconds": config["seconds"]})
        finally:
            result["agent_seconds"] = round(time.monotonic() - before, 3)
            bridge.stop()
        bridge.reconcile()
        result["triggered"] = bridge.triggered or trial["scenario"] == "misleading-fixture"
        result["source"] = candidate.read_text(encoding="utf-8")
        result["diff"] = "".join(difflib.unified_diff(starter.splitlines(True), result["source"].splitlines(True),
                                                     fromfile="starter/firmware.c", tofile="candidate/firmware.c"))
        before = time.monotonic()
        try:
            result["verifier"] = grade(task, result["source"])
            result["status"] = "passed" if result["verifier"]["pass"] else "failed"
        except Exception as exc:
            bridge.infrastructure_error = "Verifier infrastructure: " + str(exc)
        result["grader_seconds"] = round(time.monotonic() - before, 3)
        if bridge.infrastructure_error:
            result["status"], result["reason"] = "invalid", bridge.infrastructure_error
    return result



