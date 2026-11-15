"""Host-owned assertions. Only the candidate, header and driver enter the container."""
import json
import subprocess

import uuid


from .common import IMAGE, ROOT, TASKS


class InfrastructureError(RuntimeError):
    pass


def docker(*args, stdin=None, timeout=20):
    try:
        result = subprocess.run(["docker", *args], input=stdin, capture_output=True,
                                text=True, errors="replace", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise InfrastructureError(f"Docker unavailable or timed out: {exc}") from exc
    if result.returncode in (125, 126, 127) or "error during connect" in result.stderr.lower():
        raise InfrastructureError(result.stderr[:600])
    return result


def checked(*args):
    result = docker(*args)
    if result.returncode:
        raise InfrastructureError(result.stderr[:600] or "Docker operation failed")
    return result


def grade(task, source, reserved=True):
    cases = list(TASKS[task]["public"])
    if reserved:
        cases += json.loads((ROOT / "verifier" / f"{task}.json").read_text())
    name = "firmwarebench-" + uuid.uuid4().hex
    # A read-only root, a small writable tmpfs and an unprivileged user are shared
    # by the compiler and executable. No host path or credentials are mounted.
    checked("run", "-d", "--name", name, "--network", "none", "--read-only",
            "--cap-drop=ALL", "--security-opt", "no-new-privileges", "--user", "65534:65534",
            "--memory", "192m", "--memory-swap", "192m", "--cpus", "1", "--pids-limit", "40",
            "--tmpfs", "/tmp:rw,exec,nosuid,size=24m,mode=1777", "-w", "/tmp",
            IMAGE, "sleep", "90")
    try:
        sources = {"firmware.c": source}
        for filename in ("firmware.h", "driver.c"):
            sources[filename] = (ROOT / "tasks" / task / filename).read_text(encoding="utf-8")
        for filename, contents in sources.items():
            copy = docker("exec", "-i", name, "sh", "-c", 'cat > "$1"', "copy", filename, stdin=contents)
            if copy.returncode:
                raise InfrastructureError(copy.stderr[:600])
        compile_result = docker("exec", name, "sh", "-c",
            "ulimit -f 1024; timeout -k 1 8 gcc -std=c11 -Wall -Wextra -Werror -O1 "
            "firmware.c driver.c -o /tmp/check >build.log 2>&1; rc=$?; head -c 3000 build.log; exit $rc")
        assertions = [{"name": "compile", "scope": "build", "pass": compile_result.returncode == 0,
                       "detail": compile_result.stdout[:3000] or compile_result.stderr[:1000]}]
        if compile_result.returncode == 0:
            for i, case in enumerate(cases):
                out = docker("exec", "--user", "65533:65533", "-i", name, "sh", "-c",
                    "ulimit -f 8; timeout -k 1 2 ./check >actual 2>errors; rc=$?; "
                    "head -c 800 actual; head -c 300 errors >&2; exit $rc", stdin=case["input"])
                assertions.append({"name": case["name"], "scope": "public" if i < len(TASKS[task]["public"]) else "reserved",
                    "pass": out.returncode == 0 and out.stdout == case["expected"],
                    "expected": case["expected"], "actual": out.stdout, "exit": out.returncode,
                    "detail": out.stderr[:300]})
        return {"pass": all(a["pass"] for a in assertions), "assertions": assertions}
    finally:
        docker("rm", "-f", name)


