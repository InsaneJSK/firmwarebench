import argparse
import json
import threading
from pathlib import Path

from . import store
from .app import Experiment


def main():
    p = argparse.ArgumentParser(description="FirmwareBench pilot")
    sub = p.add_subparsers(dest="action", required=True)
    serve = sub.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path)
    run.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.action == "serve":
        import uvicorn
        uvicorn.run("firmwarebench.app:app", host="127.0.0.1", port=args.port)
    else:
        from .worker import worker
        cfg = Experiment.model_validate_json(args.config.read_text(encoding="utf-8")) if args.config else Experiment()
        store.initialize()
        eid = store.schedule(cfg.model_dump())
        print("Experiment", eid, flush=True)
        worker(threading.Event(), once=True)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(store.export(eid), indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
