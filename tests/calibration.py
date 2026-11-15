"""Run both graders against starters, partial edits and complete repairs."""
from firmwarebench.common import ROOT
from firmwarebench.grader import grade


def calibrate():
    for task in ("uart", "ring"):
        starter = (ROOT / "tasks" / task / "firmware.c").read_text()
        if task == "uart":
            good = starter.replace("    p->used = 0;\n", "", 1)
            partial = starter.replace("    p->used = 0;", "    if (!count) p->used = 0;", 1)
        else:
            full = "if (r->count == CAPACITY) return;"
            good = starter.replace(full, "if (r->count == CAPACITY) {\n        r->tail = (r->tail + 1) % CAPACITY;\n        --r->count;\n    }")
            partial = starter.replace(full, "if (r->count == CAPACITY) { r->tail = 1; --r->count; }")
        for label, candidate in [("broken", starter), ("partial", partial), ("known-good", good)]:
            verdict = grade(task, candidate)
            print(task, label, [(a["name"], a["pass"]) for a in verdict["assertions"]], flush=True)
            assert verdict["pass"] == (label == "known-good")
            if label == "partial":
                assert all(a["pass"] for a in verdict["assertions"] if a["scope"] != "reserved")
                assert any(not a["pass"] for a in verdict["assertions"] if a["scope"] == "reserved")


if __name__ == "__main__":
    calibrate()
