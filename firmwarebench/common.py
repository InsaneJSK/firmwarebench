"""Task discovery, limits, and content fingerprints."""
from hashlib import sha256
from pathlib import Path
import json
import os
import platform

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get("FIRMWAREBENCH_DATA", ROOT / ".firmwarebench")).resolve()
IMAGE = "gcc:14.2.0-bookworm@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c"
AGENTS = {"inspect": "Inspect ReAct", "smolagents": "smolagents ToolCallingAgent"}
SCENARIOS = ("clean", "broken-tool", "model-outage", "misleading-fixture")
TASKS = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
         for p in sorted((ROOT / "tasks").glob("*/task.json")) if (p.parent / "firmware.c").is_file()}
ROUTES = tuple(os.environ.get("FIRMWAREBENCH_ROUTES", "ollama/qwen2.5:3b").split(","))
GATEWAY = os.environ.get("BIFROST_URL", "http://127.0.0.1:14808").rstrip("/")


def fingerprint(files):
    d = sha256()
    for path in sorted(files):
        d.update(path.relative_to(ROOT).as_posix().encode() + b"\0")
        d.update(path.read_bytes().replace(b"\r\n", b"\n"))
    return d.hexdigest()


SUITES = {"embedded-c/1": tuple(TASKS), "embedded-c/1.1": ("uart",)}
DIAGNOSTIC = ROOT / "tasks" / "uart-diagnostic" / "task.json"


def task_spec(task, suite):
    spec = TASKS[task]
    if suite == "embedded-c/1.1" and task == "uart":
        return {**spec, **json.loads(DIAGNOSTIC.read_text(encoding="utf-8"))}
    return spec


def versions(task, route, suite):
    from importlib.metadata import version
    from urllib.request import urlopen
    model_digest = None
    if route.startswith("ollama/"):
        try:
            with urlopen(os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434") + "/api/tags", timeout=2) as resp:
                tags = json.load(resp)["models"]
                model_digest = next((m["digest"] for m in tags if m["name"] == route.split("/", 1)[1]), None)
        except (OSError, ValueError, KeyError):
            pass
    return {"local_model_digest": model_digest, "suite": suite, "task": task_spec(task, suite)["version"],
            "task_sha256": fingerprint([*(ROOT / "tasks" / task).glob("*"), *([DIAGNOSTIC] if suite == "embedded-c/1.1" else [])]),
            "grader_sha256": fingerprint([ROOT / "verifier" / f"{task}.json",
                                          ROOT / "firmwarebench" / "grader.py"]),
            "runner_sha256": fingerprint((ROOT / "firmwarebench").glob("*.py")),
            "gcc_image": IMAGE, "gateway": "Bifrost v1.5.0 (bundled configuration)",
            "inspect-ai": version("inspect-ai"), "smolagents": version("smolagents"),
            "python": platform.python_version(), "host": platform.platform()}




