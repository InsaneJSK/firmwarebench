import unittest
from firmwarebench.metrics import compare, metrics


def event(kind, **fields):
    return {"kind":kind, "at":0, "data":fields}


class AccountingTests(unittest.TestCase):
    def test_fallback_deduplication_and_missing_usage(self):
        log = event("gateway", id="serving", request_id="r", provider="ollama", model="m",
                    status="success", usage={"total_tokens":31}, fallback=1)
        primary = event("gateway", id="outage", request_id="r", provider="offline", model="m",
                        status="error", http_status=503, fallback=0)
        decision = event("decision", request_id="r", requested="offline/m")
        response = event("response", request_id="r", provider="ollama", model="m", usage={"total_tokens":31},
                         tools_requested=["submit"])
        vals = metrics({"events":[decision,response,primary,log,log]})
        self.assertEqual((vals["tokens"],vals["provider_attempts"],vals["cost"]), (31,2,0))
        self.assertEqual((vals["steps"],vals["finish_calls"],vals["gateway_recovery"]), (2,1,True))
        missing = metrics({"events":[decision,response]})
        self.assertIsNone(missing["tokens"])
        self.assertIsNone(missing["cost"])
        self.assertEqual(missing["known_tokens"],31)

    def test_json_completion_counts_once_with_repeated_event_delivery(self):
        decision = event("decision", request_id="r", requested="groq/m")
        response = event("response", request_id="r", tools_requested=[])
        native = event("framework_call", id="f1", request_id="r", name="final_answer", status="ok")
        values = metrics({"events": [decision, response, native, native]})
        self.assertEqual((values["finish_calls"], values["tool_calls"], values["steps"]), (1, 1, 2))

    def test_wire_and_native_completion_are_matched_per_decision(self):
        events = [event("decision", request_id=rid, requested="groq/m") for rid in ("r1", "r2")]
        events += [event("response", request_id="r1", tools_requested=["final_answer"]),
                   event("framework_call", id="f1", request_id="r1", name="final_answer", status="failed"),
                   event("response", request_id="r2", tools_requested=[]),
                   event("framework_call", id="f2", request_id="r2", name="final_answer", status="ok")]
        values = metrics({"events": events})
        self.assertEqual((values["finish_calls"], values["tool_calls"], values["steps"]), (2, 2, 4))

    def test_multiple_calls_in_one_decision_keep_their_multiplicity(self):
        events = [event("decision", request_id="r", requested="groq/m"),
                  event("response", request_id="r", tools_requested=["final_answer", "final_answer"]),
                  event("framework_call", id="f1", request_id="r", name="final_answer", status="ok"),
                  event("framework_call", id="f2", request_id="r", name="final_answer", status="ok")]
        self.assertEqual(metrics({"events": events})["finish_calls"], 2)

    def test_rates_charge_failed_trials_and_exclude_invalid_from_success(self):
        template = dict(agent="inspect",task="uart",scenario="broken-tool",agent_seconds=2)
        rows = [{**template,"id":str(n),"status":state,"triggered":trigger,"metrics":{"cost":cost}}
                 for n,(state,trigger,cost) in enumerate([("passed",True,.15),("failed",False,.35),("invalid",True,.1)])]
        group = compare(rows)[0]
        self.assertEqual([group[k] for k in ("valid","passed","invalid","triggered","recovered")],[2,1,1,1,1])
        self.assertAlmostEqual(group["cost_per_success"],.6)
        rows[1]["metrics"]["cost"] = None
        self.assertIsNone(compare(rows)[0]["cost_per_success"])


if __name__ == "__main__":
    unittest.main()
