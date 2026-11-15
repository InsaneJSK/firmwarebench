"""SQLite-backed scheduling and crash recovery for a single local worker."""
from contextlib import contextmanager
import itertools
import json
import sqlite3
import time
import uuid

from .common import DATA
from .metrics import compare, metrics


@contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / "bench.sqlite", timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def initialize():
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript("""
            CREATE TABLE IF NOT EXISTS experiments(id TEXT PRIMARY KEY, created REAL, config TEXT);
            CREATE TABLE IF NOT EXISTS trials(id TEXT PRIMARY KEY, experiment TEXT, agent TEXT, task TEXT,
              scenario TEXT, repetition INTEGER, queued REAL, status TEXT, result TEXT);
            CREATE INDEX IF NOT EXISTS trials_by_experiment ON trials(experiment);
            CREATE TABLE IF NOT EXISTS events(trial TEXT, seq INTEGER PRIMARY KEY, payload TEXT);
            CREATE INDEX IF NOT EXISTS events_by_trial ON events(trial,seq);
        """)


def recover():
    with db() as c:
        c.execute("UPDATE trials SET status='invalid',result=? WHERE status='running'",
                  (json.dumps({"reason": "Worker interrupted before independent grading."}),))


def schedule(config):
    now, eid = time.time(), uuid.uuid4().hex
    with db() as c:
        c.execute("INSERT INTO experiments VALUES(?,?,?)", (eid, now, json.dumps(config)))
        for rep, task, scenario, agent in itertools.product(range(1, config["repeats"]+1),
                config["tasks"], config["scenarios"], config["agents"]):
            c.execute("INSERT INTO trials VALUES(?,?,?,?,?,?,?,?,NULL)",
                      (uuid.uuid4().hex, eid, agent, task, scenario, rep, now, "queued"))
    return eid


def claim():
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        row = c.execute("SELECT * FROM trials WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone()
        if row is None:
            return None
        c.execute("UPDATE trials SET status='running' WHERE id=?", (row["id"],))
        config = c.execute("SELECT config FROM experiments WHERE id=?", (row["experiment"],)).fetchone()[0]
        return dict(row), json.loads(config)


def record(tid, event):
    with db() as c:
        c.execute("INSERT INTO events(trial,payload) VALUES(?,?)", (tid, json.dumps(event)))


def finish(tid, result):
    without_events = {k:v for k,v in result.items() if k != "events"}
    with db() as c:
        c.execute("UPDATE trials SET status=?,result=? WHERE id=?",
                  (result["status"], json.dumps(without_events), tid))


def experiments():
    with db() as c:
        return [{**dict(r), "config": json.loads(r["config"])} for r in
                c.execute("SELECT * FROM experiments ORDER BY created DESC")]


def export(eid):
    with db() as c:
        exp = c.execute("SELECT * FROM experiments WHERE id=?", (eid,)).fetchone()
        if exp is None:
            raise KeyError(eid)
        rows = c.execute("SELECT * FROM trials WHERE experiment=? ORDER BY rowid", (eid,)).fetchall()
        event_rows = c.execute("SELECT trial,payload FROM events JOIN trials ON trials.id=events.trial "
                               "WHERE trials.experiment=? ORDER BY seq", (eid,)).fetchall()
    by_id = {r["id"]:[] for r in rows}
    for event in event_rows:
        by_id[event["trial"]].append(json.loads(event["payload"]))
    trials = []
    for row in rows:
        t = dict(row)
        t.update(json.loads(t.pop("result") or "{}"))
        t["events"] = by_id[t["id"]]
        t["metrics"] = metrics(t)
        trials.append(t)
    return {"schema": "firmwarebench.experiment.v1", "id": eid, "created": exp["created"],
            "config": json.loads(exp["config"]), "trials": trials, "comparison": compare(trials)}
