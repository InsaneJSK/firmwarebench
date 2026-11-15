# FirmwareBench

FirmwareBench runs Inspect ReAct and smolagents ToolCallingAgent against the same embedded C repair tasks. Its dashboard links each comparison cell to a trial’s tool attempts, actual model route, candidate patch and independent verifier assertions.

## Public demo and bring-your-own-provider runs

[Open the evidence explorer](https://insanejsk.github.io/firmwarebench/) · [Pitch PDF](docs/pitch.pdf) · [Browser presentation](https://insanejsk.github.io/firmwarebench/pitch.html)

The public demo is a static evidence explorer: compare the recorded Groq and Qwen experiments, inspect patches and reserved checks, and download the original JSON. It does not run new jobs or collect provider keys.

FirmwareBench itself is a self-hosted benchmarking platform. Run the worker and isolated Docker verifier in your own environment, then connect your model provider through Bifrost. Hosted providers use your own API credentials (BYOK); local Ollama routes are supported too. The frontend uses HTML/CSS/JavaScript, the API uses FastAPI, and SQLite stores experiments and evidence.

GitHub Pages serves the checked-in `docs/` directory from `main`. After changing the dashboard renderer or saved evidence, regenerate the static demo with `python scripts/build_demo.py`. The build copies only the selected public exports and frontend assets. Keep `.env`, reports, databases and runtime directories outside `docs/`.

## Open the saved experiment

Install Python 3.11 and uv. From the root of this repository, run:

```sh
uv sync --locked --python 3.11
uv run --locked python -m firmwarebench serve
```

Open [the local dashboard](http://127.0.0.1:8765). **Saved benchmark** reads `examples/comparison.json`. Select a pass-count cell, choose a repetition and expand the timeline or verifier checks. **Export JSON** downloads all evidence. **Open export** opens a JSON file in the browser without uploading it. The saved view requires no provider key, Ollama or Docker. Open the eight-slide pitch in `docs/pitch.pdf`. The browser version in `docs/pitch.html` supports arrow keys and printing.

The included 3B experiment recorded 0/24 verified passes for each framework. Forty-five candidates changed the source. Bifrost recovered all 12 controlled outages. All 201 provider attempts were accounted for, with 319,690 reported tokens and zero estimated local provider fees. Cost per successful trial is undefined in this experiment.

## Run the hosted Groq pilot

The full Groq benchmark is saved in `examples/groq-comparison.json`: Inspect passed 3/23 valid trials with one invalid, and smolagents passed 11/19 valid trials with five invalid. Each agent had 24 scheduled trials. The pitch shows this full matrix alongside Qwen and distinguishes the later focused pilot and its changed budgets.

The latest focused protocol-repair pilot is `examples/groq-repair-pilot-v2.json`: Inspect passed 3/4 and smolagents passed 2/4, with 0 invalid trials. It covers both original tasks under transient-test and model-outage disruptions with six turns and 12 tool attempts. All candidates received matching independent regrades. The earlier exploratory failures are retained in `examples/groq-repair-pilot-attempt-01.json`.

Both agents passed the same UART outage experiment in `examples/groq-uart-two-agent-pass.json`. Inspect submitted through `submit` and smolagents through `final_answer`. Each candidate passed all seven original checks in a fresh-container regrade. That historical pilot used narrowed tool selection. The current Groq bridge retains all native tools with automatic selection, refreshes the mutable source snapshot, and gives both agents public-test and completion guidance. Guarded line edits reject stale source. Decision events expose the guidance and snapshot refresh count. Groq still generates every action and its arguments.

Inspect ReAct repaired the original UART parser after the controlled HTTP 503. Its submitted source passed compilation, all three public tests and all three reserved tests, including an independent regrade. In the same two-trial pilot, smolagents produced a source that passed all seven checks, but Groq rejected its final required tool call. FirmwareBench recorded that trial as invalid. Open `examples/groq-uart-feedback.json` in the dashboard for both patches and the gateway events. The two earlier hosted attempts are preserved in `examples/groq-uart-outage.json` and `examples/groq-uart-outage-02.json`.

Use Groq's free organization and a key in the ignored repository-root `.env` file (`GROQ_API_KEY=...`). Model calls send the public issue, candidate code and public tool observations to Groq. Firmware compilation and reserved verification stay in short-lived local Docker containers. This separate gateway has no Ollama provider. The current focused pilot covers both original tasks and both agents under a transient public-test failure and an injected model HTTP 503. It allows six decision turns, 12 tool attempts and 300 seconds per trial, with 30-second model-request spacing. Historical four-turn results remain separate.

From the repository root in PowerShell:

```powershell
docker compose -f compose.groq.yaml up -d
$env:BIFROST_URL = 'http://127.0.0.1:14809'
$env:FIRMWAREBENCH_ROUTES = 'groq/openai/gpt-oss-20b'
$env:FIRMWAREBENCH_DATA = Join-Path (Get-Location) '.firmwarebench/groq'
uv run --locked python -m firmwarebench run --config examples/groq-repair-pilot-v2-config.json --output .firmwarebench/groq/new-pilot.json
```

Open the generated JSON in the dashboard with **Open export**. A subsequent run should use a fresh output filename. The worker spaces requests on this Groq route by 30 seconds, including across consecutive trials. Recorded baseline requests peaked at 2,652 Qwen tokens. Different tokenization, longer reasoning and concurrent organization traffic may still cause HTTP 429. Review the organization's actual limits and remaining quota before scaling up. [Groq rate limits](https://console.groq.com/docs/rate-limits) · [Account limits](https://console.groq.com/settings/organization/limits)

With those environment variables set, `uv run --locked python -m firmwarebench serve` opens the worker for hosted runs. The hosted setup form starts with the two-trial UART outage pilot using six turns and 12 tool attempts. The `show_edit_feedback` experiment option supplies both agents with the numbered candidate after every edit attempt and documents the empty argument object for public tests. Its default in the experiment schema is off. The Groq bridge requests low reasoning effort and returns public assistant content and tool calls to the frameworks. This keeps provider-specific reasoning metadata out of subsequent requests. Stop the hosted gateway with `docker compose -f compose.groq.yaml stop`.

## Reproduce the local Qwen experiment

The live path uses Python on the host, Docker with Linux containers and Ollama. Docker Desktop on Windows was used for the recorded experiment. On Linux the gateway container must be able to reach the host’s Ollama service using the Compose host-gateway entry. Start Docker and Ollama first.

```sh
ollama pull qwen2.5:3b
docker pull gcc:14.2.0-bookworm@sha256:b99b86a28812b1e6453a231a947dc43d76fe192788a12f344a9b568bf9f5d24c
docker compose up -d
uv run --locked python -m tests.calibration
uv run --locked python -m firmwarebench serve
```

Select **New experiment**. Choose the two agents, tasks, version, route, scenarios, repeats and limits. The form displays the trial count. The dashboard polls progress. When a worker restarts it marks the in-flight trial invalid, keeps completed evidence and resumes queued work. One local worker owns a database at a time.

For unattended execution, close the dashboard server first so the CLI can own the worker. The pilot configuration runs four UART trials. The matrix configuration runs 48. Each new invocation schedules a distinct experiment. Preserve the included evidence by choosing a new output path.

```sh
uv run --locked python -m firmwarebench run --config examples/pilot-config.json --output .firmwarebench/pilot.json
uv run --locked python -m firmwarebench run --config examples/matrix-config.json --output .firmwarebench/matrix.json
uv run --locked python -m unittest discover -s tests
```

Stop the dashboard with Ctrl+C. `docker compose down` stops the two gateway services. Local run data lives in the ignored `.firmwarebench/` directory. Phase reports live in the ignored `reports/` directory.

## Tasks, faults and grading

| Task v1.0.0 | Authoritative contract | Reserved checks |
| --- | --- | --- |
| UART parser | A5 sync followed by channel and value. Preserve partial frames across any read, skip noise and allow A5 in the payload. | Bytewise reads, empty reads, adjacent frames and payload sync bytes |
| Telemetry ring | Keep the newest four samples, overwrite the oldest on overflow, return FIFO order and −1 on empty. | Repeated wraps, interleaved refill and complete drains |

Each agent starts in a fresh temporary directory with the same issue, header, initial source, limits and shared tool interface. Its framework retains its own system prompt and completion protocol. Tools read the source, edit a numbered line or unique substring, and run public tests. The independent verifier takes only the final source plus immutable header and driver and compares process output against host-owned expected values. Each invocation starts a disposable network-disabled GCC container with a read-only root, separate unprivileged users, CPU/memory/PID/file limits and timeouts. Compiler errors are candidate failures. Missing Docker or a broken grader invalidates the trial.

| Scenario | Trigger and attribution |
| --- | --- |
| Clean | Standard route and tools |
| Broken tool | First actual public-test invocation returns a transient error. A later successful test call is visible as an agent retry. A trial avoiding the tool stays untriggered. |
| Model outage | First decision uses a controlled provider returning HTTP 503. Bifrost selects the configured route as fallback. A gateway error row proves the trigger. A successful fallback row identifies gateway recovery. |
| Misleading fixture | An obsolete archive note accompanies the authoritative issue. The delivery event and relevant behavioral assertion show exposure and outcome. |

## Measurement and evidence

- **Success** is passed / valid trials. Invalid trials have their own count. The comparison also shows the percentage-point change from clean and verified passes / valid triggered trials. A successful gateway fallback and a successful firmware repair are separately observable.
- **Steps** count admitted model decisions plus tool attempts. **Tool calls** include shared tool invocations, failed or denied operations, retries and framework completion calls requested in model responses. Framework completion attempts are counted once and displayed separately. The smolagents adapter records native `final_answer` execution (including JSON-text replies parsed by the framework) as a `framework_call` event. Counts match this evidence to structured provider requests by decision and function, preventing double-counting; failed native attempts also count. These events do not consume the shared-tool budget. Inspect and smolagents keep their native stopping behavior. Historical exports retain their original measurements and may omit JSON-parsed completions; new runs record them directly.
- **Tokens** sum attributable usage once per Bifrost attempt ID. A matching client response fills a missing success log without counting it twice. Unknown usage remains null. The controlled 503 happens before inference and carries zero billable tokens. Unknown internal retry usage reduces coverage.
- **Cost** uses gateway-reported USD when present. `local-inference-fee-v1` assigns zero provider fees to local Ollama and the controlled 503. Electricity and hardware are excluded. Missing prices stay null. Cost per verified success includes costs from unsuccessful and invalid attempts with attributable cost. A missing cost or zero successes produces an unavailable figure.
- **Execution time** is wall time for the adapter process, including framework initialization, model inference and public tools. Queue delay and final verification are recorded separately. A hard agent deadline can end the adapter while an already admitted gateway call finishes and is reconciled.
- **Versions** include task and verifier content hashes, runner hash, agent versions, host runtime, toolchain image digest and the locally available model digest. The recorded Qwen2.5 3B digest is `357c53fb659c5076de1d65ccb0b397446227b71a42be9d1603d46168015c9e4b`. Check the Ollama tags API to compare installations.

The export schema is `firmwarebench.experiment.v1`. Top-level fields are `id`, `created` (Unix seconds), `config`, `trials` and `comparison`. Each finished trial carries its dimensions, versions, status, timing, observed events, candidate source, unified diff, verifier and derived metrics. Event timestamps are seconds since trial start. Logical request IDs link decisions and responses to de-duplicated gateway attempt IDs and fallback parent IDs. Usage coverage includes numerators and denominators. Blank or null metrics mean unavailable. The dashboard displays the same JSON that it exports.

## Supplemental UART experiment

Open `examples/recovery.json` with **Open export** to inspect the two-agent Qwen2.5 7B outage comparison. To reproduce it, pull `qwen2.5:7b`, add `ollama/qwen2.5:7b` to `FIRMWAREBENCH_ROUTES`, and use `examples/recovery-config.json` with the CLI. The 7B model uses the Apache 2.0 license. Its recorded digest is `845dbda0ea48ed749caafd9e6037047aa19acfcfd82e704d7ca97d631a0b697e`. This experiment uses a different model and budget and is reported separately from the main matrix.

The selectable suite `embedded-c/1.1` adds a public split-read diagnostic to UART v1.1.0. The starter, driver and reserved expectations match v1.0.0. Both agents ran this version separately under the 3B route; both gateway fallbacks succeeded and neither candidate passed verification. Its complete export is `examples/diagnostic.json` and its reproducible settings are in `examples/diagnostic-config.json`. The 7B comparison likewise produced two successful gateway fallbacks and zero passing candidates. These supplemental trials are excluded from the 48-trial baseline.

## Services and diagnostics

- Bifrost listens on [localhost port 14808](http://127.0.0.1:14808). The internal outage service deliberately returns 503. The Compose volume retains gateway logs. The trial bridge exposes only the shared tools and the per-trial model endpoint on loopback.
- If a live run is invalid, open its reason and timeline. Check `docker compose ps`, `docker compose logs bifrost`, `docker version`, and `ollama list`. A first compile needs the pinned GCC image available locally.
- Configure an existing Bifrost deployment using `BIFROST_URL`, an optional `BIFROST_API_KEY` and comma-separated `FIRMWAREBENCH_ROUTES`. A custom gateway needs the same logging headers, provider logs and controlled offline route. For recording a local model fingerprint, `OLLAMA_URL` defaults to the host’s port 11434. Use `FIRMWAREBENCH_DATA` to select a separate database directory. Provider secrets stay with the gateway or worker.
- For a teammate’s replay check, copy the repository including the saved JSON, install from the lockfile, open the saved experiment and compare a trial ID, patch, reserved assertion and usage count against the export. Repeat the four-trial pilot to check a second machine’s live integration. Differences between model generations are possible.

## Original work and dependencies

The task fixtures, held-out checks, calibration edits, worker, adapters, fault bridge, measurement rules, dashboard and pitch are original project material. No benchmark datasets or third-party task solutions were copied. The agent decision loops are upstream components. Dependencies and container images are fetched during setup. Model weights remain with Ollama.

| Component | Role and upstream license |
| --- | --- |
| [Inspect AI](https://github.com/UKGovernmentBEIS/inspect_ai) | ReAct agent and evaluation runtime, MIT |
| [smolagents](https://github.com/huggingface/smolagents/tree/v1.22.0) | ToolCallingAgent, Apache-2.0 |
| [OpenAI Python client](https://github.com/openai/openai-python/tree/v2.26.0) | Chat-compatible client, Apache-2.0 |
| [Bifrost](https://github.com/maximhq/bifrost/tree/transports/v1.5.0) | Gateway, local request logs and fallback routing, Apache-2.0 |
| [Caddy](https://github.com/caddyserver/caddy) | Controlled HTTP 503 fixture, Apache-2.0 |
| [FastAPI](https://github.com/fastapi/fastapi) and [Uvicorn](https://github.com/encode/uvicorn) | Local dashboard API and server, MIT and BSD-3-Clause respectively |
| [GCC](https://gcc.gnu.org/onlinedocs/gcc/Copying.html) | Pinned compiler image, GCC under GPLv3+; individual image components have their own licenses |
| [Qwen2.5 3B Instruct](https://huggingface.co/Qwen/Qwen2.5-3B-Instruct/blob/main/LICENSE) | Local model under the Qwen Research License Agreement |

Host compilation is the measurement environment. ADC calibration, Renode/Zephyr and physical board tests are future work. Three repetitions per cell support inspecting outcomes and failure modes; they provide limited precision for ranking agents.



