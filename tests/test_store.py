import tempfile

import unittest
from pathlib import Path
from unittest.mock import patch

from firmwarebench import store
from firmwarebench.app import Experiment


class StoreTests(unittest.TestCase):
    def test_completed_trials_survive_interruption(self):
        cfg = Experiment(tasks=["uart"], repeats=1, scenarios=["clean", "broken-tool"]).model_dump()
        with tempfile.TemporaryDirectory() as temp, patch.object(store, "DATA", Path(temp)):
            store.initialize()
            eid = store.schedule(cfg)
            first, _ = store.claim()
            store.record(first["id"], {"kind":"fault", "at":0.1, "data":{"profile":"broken-tool"}})
            store.finish(first["id"], {"status":"passed", "events":[], "agent_seconds":1.0})
            second, _ = store.claim()
            store.recover()
            data = store.export(eid)
            states = {t["id"]:t for t in data["trials"]}
            self.assertEqual(len(states),4)
            self.assertEqual(states[first["id"]]["status"],"passed")
            self.assertEqual(len(states[first["id"]]["events"]),1)
            self.assertEqual(states[second["id"]]["status"],"invalid")
            self.assertEqual(sum(t["status"]=="queued" for t in states.values()),2)
            self.assertEqual(states[second["id"]]["metrics"]["tokens"],None)


if __name__ == "__main__":
    unittest.main()

