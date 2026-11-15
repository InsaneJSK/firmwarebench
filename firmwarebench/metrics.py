"""Aggregate observable events without turning missing measurements into zeroes."""
from collections import Counter, defaultdict


def metrics(trial):
    events = trial.get("events", [])
    def of(kind):
        return [e["data"] for e in events if e["kind"] == kind]
    decisions = of("decision")
    tools = of("tool")
    attempts = {a["id"]: a for a in of("gateway")}.values()
    responses = {r["request_id"]: r for r in of("response")}
    by_call = defaultdict(list)
    for a in attempts:
        by_call[a["request_id"]].append(a)
    tokens, cost, covered, cost_covered, records = 0, 0, 0, 0, 0
    served = set()
    for call in decisions:
        rid = call["request_id"]
        rows = list(by_call[rid])
        response = responses.get(rid, {})
        if not rows or (response and not any(a["status"] == "success" for a in rows)):
            rows.append({**response, "status": "success" if response else "unknown"})
        if call["requested"].startswith("offline/") and not any(a.get("provider") == "offline" for a in rows):
            rows.append({"status": "unknown"})
        for row in rows:
            records += 1
            provider = row.get("provider")
            if row["status"] == "success" and provider and row.get("model"):
                served.add(provider + "/" + row["model"])
            usage = row.get("usage") or {}
            # The fixture returns a fixed 503 before inference, with no billable request.
            fixture = provider == "offline" and row.get("http_status") == 503
            if fixture or usage.get("total_tokens") is not None:
                covered += 1
                tokens += 0 if fixture else usage["total_tokens"]
            if row.get("cost") is not None:
                cost += row["cost"]
                cost_covered += 1
            elif provider == "ollama" or fixture:
                cost_covered += 1
            # Provider-internal retries lack individually attributable usage.
            records += row.get("retries") or 0
    # Match execution evidence to provider requests, retaining legacy wire-only counts.
    requested = Counter((rid, name) for rid, r in responses.items()
                        for name in r.get("tools_requested", []) if name in ("submit", "final_answer"))
    executions = {c["id"]: c for c in of("framework_call")}
    observed = Counter((c["request_id"], c["name"]) for c in executions.values()
                       if c.get("name") in ("submit", "final_answer"))
    framework_calls = sum(max(requested[key], observed[key]) for key in requested.keys() | observed.keys())
    calls = len(tools) + framework_calls
    return {"steps": len(decisions) + calls, "turns": len(decisions), "tool_calls": calls,
            "shared_calls": len(tools), "finish_calls": framework_calls,
            "failed_calls": sum(t["status"] == "failed" for t in tools),
            "denied_calls": sum(t["status"] == "denied" for t in tools),
            "provider_attempts": records, "usage_covered": covered, "cost_covered": cost_covered,
            "known_tokens": tokens, "tokens": tokens if records and covered == records else None,
            "known_cost": cost, "cost": cost if records and cost_covered == records else None,
            "cost_basis": "provider-reported or local-inference-fee-v1 (USD, excludes hosting and energy)",
            "served": sorted(served),
            "gateway_recovery": any(a["fallback"] and a["status"] == "success" for a in attempts)}


def compare(trials):
    groups = defaultdict(list)
    for t in trials:
        groups[(t["agent"], t["task"], t["scenario"])].append(t)
    rows = []
    for (agent, task, scenario), group in groups.items():
        finished = [t for t in group if t["status"] in ("passed", "failed", "invalid")]
        valid = [t for t in finished if t["status"] != "invalid"]
        passed = sum(t["status"] == "passed" for t in valid)
        triggered = [t for t in valid if t.get("triggered")]
        values = [t["metrics"] for t in finished if "metrics" in t]
        costs = [m["cost"] for m in values]
        total_cost = sum(costs) if costs and all(v is not None for v in costs) and len(costs)==len(finished) else None
        rows.append({"agent": agent, "task": task, "scenario": scenario, "scheduled": len(group),
                     "valid": len(valid), "passed": passed, "invalid": len(finished)-len(valid),
                     "triggered": len(triggered), "recovered": sum(t["status"]=="passed" for t in triggered),
                     "cost_per_success": total_cost/passed if total_cost is not None and passed else None,
                     "cost_total": total_cost,
                     "mean_seconds": sum(t.get("agent_seconds", 0) for t in finished)/len(finished) if finished else None,
                     "ids": [t["id"] for t in group]})
    return rows
