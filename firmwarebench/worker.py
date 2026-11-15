import os
import time

from . import store
from .common import DATA
from .runner import execute


def worker(stop, once=False):
    store.initialize()
    # An OS advisory lock is automatically released after a process crash.
    with (DATA / "worker.lock").open("a+b") as guard:
        guard.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(guard.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if once:
                raise RuntimeError("A worker is already active for this database.")
            return
        store.recover()
        while not stop.is_set():
            work = store.claim()
            if not work:
                if once:
                    return
                stop.wait(0.5)
                continue
            trial, config = work
            try:
                result = execute(trial, config, lambda e: store.record(trial["id"], e))
            except Exception as exc:
                result = {"status": "invalid", "reason": f"{type(exc).__name__}: {str(exc)[:500]}"}
            store.finish(trial["id"], result)
            print(trial["agent"], trial["task"], trial["scenario"], trial["repetition"],
                  result["status"], flush=True)
