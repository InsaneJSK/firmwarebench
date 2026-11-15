from contextlib import asynccontextmanager
import json
import threading

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import store
from .common import AGENTS, ROOT, ROUTES, SCENARIOS, TASKS, SUITES, task_spec
from .worker import worker


class Experiment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="Firmware repair comparison", min_length=1, max_length=100)
    agents: list[str] = Field(default_factory=lambda:list(AGENTS))
    suite: str = "embedded-c/1"
    tasks: list[str] = Field(default_factory=lambda:list(TASKS))
    scenarios: list[str] = Field(default_factory=lambda:list(SCENARIOS))
    route: str = ROUTES[0]
    repeats: int = Field(default=3, ge=1, le=10)
    turn_limit: int = Field(default=5, ge=1, le=20)
    tool_limit: int = Field(default=12, ge=1, le=60)
    seconds: int = Field(default=120, ge=15, le=600)
    show_edit_feedback: bool = False

    @model_validator(mode="after")
    def known_options(self):
        for selected, allowed in [(self.agents, AGENTS), (self.tasks, TASKS), (self.scenarios, SCENARIOS)]:
            if not selected or len(selected) != len(set(selected)) or set(selected)-set(allowed):
                raise ValueError("Choose at least one distinct available option in each group.")
        if len(self.agents) != 2 or self.route not in ROUTES or self.suite not in SUITES:
            raise ValueError("Select the two available agents, a configured route and a known suite.")
        if set(self.tasks) - set(SUITES[self.suite]):
            raise ValueError("This task is unavailable in the selected suite.")
        return self


@asynccontextmanager
async def lifespan(app):
    store.initialize()
    stop = threading.Event()
    thread = threading.Thread(target=worker, args=(stop,), daemon=True)
    thread.start()
    yield
    stop.set()


app = FastAPI(title="FirmwareBench", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/catalog")
def catalog():
    return {"agents": AGENTS, "tasks": {k:v["name"] for k,v in TASKS.items()}, "scenarios": SCENARIOS,
            "suites": {s:{t:task_spec(t,s)["version"] for t in ts} for s,ts in SUITES.items()},
            "routes": ROUTES, "suite": "embedded-c/1", "versions": {k:v["version"] for k,v in TASKS.items()}}


@app.get("/api/experiments")
def list_experiments():
    return store.experiments()


@app.post("/api/experiments", status_code=201)
def create(config: Experiment, request: Request):
    from urllib.parse import urlsplit
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Open the local dashboard to start a run.")
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise HTTPException(415, "JSON required")
    return {"id": store.schedule(config.model_dump())}


def evidence(eid):
    if eid == "saved":
        file = ROOT / "examples" / "comparison.json"
        if not file.is_file():
            raise HTTPException(404, "No saved comparison yet.")
        return json.loads(file.read_text(encoding="utf-8"))
    try:
        return store.export(eid)
    except KeyError:
        raise HTTPException(404, "Experiment not found.")


@app.get("/api/experiments/{eid}")
def show(eid: str):
    return evidence(eid)


@app.get("/api/experiments/{eid}/export")
def download(eid: str):
    return JSONResponse(evidence(eid), headers={"Content-Disposition": "attachment; filename=firmwarebench-comparison.json"})


app.mount("/assets", StaticFiles(directory=ROOT / "web"), name="assets")

