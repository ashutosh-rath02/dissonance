# CLAUDE.md

Guidance for Claude Code (or any agent) working in this repo.

## What this is

Dissonance: claim-level, citation-independent contradiction detection over LLM-evaluation papers
on arXiv. Full design doc: [plan.md](plan.md) (positioning, schemas, loop engineering, milestones
— **read this first**, it's the source of truth for scope and design decisions). Build-status
tracking: [docs/architecture.md](docs/architecture.md). Decision rationale: [docs/decisions/](docs/decisions/).

Orchestration is plain asyncio (no LangGraph — see [ADR 0001](docs/decisions/0001-orchestration-asyncio.md)).
Model provider is OpenAI, per-stage config in [configs/run.yaml](configs/run.yaml) (cheap tier for
screening/extraction, strong tier for adjudication/synthesis).

## Environment quirks (this machine)

Python, Node, and Docker are installed but **not on PATH** in either the Bash tool or PowerShell
tool session used here. Use full paths / prepend to PATH per-command rather than assuming they resolve:

```bash
/c/Python313/python.exe ...            # or: ./.venv/Scripts/python.exe once venv exists
"/c/Program Files/Docker/Docker/resources/bin/docker.exe" ...
export PATH="/c/Program Files/Docker/Docker/resources/bin:$PATH"   # needed for docker-credential-desktop lookup
```

Docker Desktop is not always running — check with `docker info`; if the daemon is down, launch
`"C:\Program Files\Docker\Docker\Docker Desktop.exe"` via PowerShell `Start-Process` and poll
`docker info` until it succeeds (took ~15s observed).

**Port 5432 is taken** by a native Windows PostgreSQL service (`postgresql-x64-18`) on this
machine, unrelated to this project — don't stop it. `docker-compose.yml` maps the pgvector
container to **host port 5433** instead; `DATABASE_URL` in `.env`/`.env.example` matches.

## Commands

```bash
# one-time setup
/c/Python313/python.exe -m venv .venv
./.venv/Scripts/python.exe -m pip install -e ".[dev]"
cp .env.example .env                      # fill OPENAI_API_KEY when extraction (Week 2) starts

# bring up postgres+pgvector
export PATH="/c/Program Files/Docker/Docker/resources/bin:$PATH"
docker compose up -d db
./.venv/Scripts/python.exe -m dissonance.graph.migrate

# ingest a corpus (the Week 1 exit test)
./.venv/Scripts/python.exe -m dissonance.scouts.run --query "LLM evaluation" --limit 50

# supervisor stub demo (no-op pipeline, proves budgets/manifest work)
./.venv/Scripts/python.exe -m dissonance.supervisor.demo

# tests + lint
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check dissonance tests
```

## Conventions

- **Nothing runs outside the Supervisor.** Any new pipeline stage wraps its work in
  `with supervisor.stage("name"): ...` and reports spend via `supervisor.spend("name", usd)`. See
  `dissonance/supervisor/core.py`. This is not optional — it's how budgets, wall-clock caps, and
  the run manifest (`runs/<run_id>/manifest.json`) stay meaningful across every stage.
- **Claim and Conflict schemas are fixed contracts** — they mirror plan.md §3.2/§3.3 exactly
  (`dissonance/graph/models.py`, `dissonance/graph/schema.sql`). Don't drift the Pydantic models
  from the SQL schema from the plan without updating all three together.
- **Loop caps are config, not hardcoded.** Retry counts, escalation tiers, and breaker thresholds
  live in `configs/run.yaml` under `stages.*` / `loops.*`, loaded via `RunConfig.load(...)`. New
  loops (re-extraction, adjudication escalation, etc.) should follow the same pattern — add a
  block to `run.yaml`, not a magic number in code.
- **Tests never make live network or LLM calls.** `tests/test_arxiv_scout.py` mocks httpx with
  `respx`; do the same for OpenAlex/Semantic Scholar/OpenAI clients as they're added. Live-network
  scripts (like `dissonance/scouts/run.py`) are for manual/CI-integration runs, not `pytest`.
- **Honesty rule (plan.md §5.2):** once the eval harness exists (Week 3), no metric gets published
  or claimed in the README without the eval that produced it landing in `evals/`.

## Current status

Week 1 (skeleton + ingestion) is done: supervisor, Postgres+pgvector schema, arXiv scout, CI.

Week 2 (extraction swarm + claim graph) is functional and verified against real papers:
`dissonance/extraction/` (fetch, extractor, validator, pipeline, run.py CLI) and
`dissonance/graph/entity_resolution.py` are in. Run it with
`python -m dissonance.extraction.run --limit N`.

Known state worth knowing before touching this code:
- **Model tier is gpt-4.1(-mini), not gpt-5(-mini)** — this OpenAI org isn't verified for gpt-5
  yet. See [ADR 0004](docs/decisions/0004-gpt-4.1-standin-for-gpt-5.md). Swap `configs/run.yaml`
  back once verified.
- **arXiv HTML export duplicates math/numbers** via hidden `<annotation>` (LaTeXML TeX-source)
  tags sitting next to the rendered glyphs — e.g. a visible "12.4%" is immediately followed by a
  hidden "12.4\%". `dissonance/extraction/fetch.py` strips these; if span-verification failures
  spike again, check whether arXiv changed its HTML export and a new duplicate-content tag needs
  stripping.
- **The model still occasionally elides quotes with "..."** despite `extraction_v1.md` explicitly
  forbidding it — real, observed against live papers, not hypothetical. The pipeline handles this
  by dropping just the offending claim rather than discarding the whole batch (see
  `extract_paper` in `dissonance/extraction/pipeline.py`), but the underlying prompt-adherence
  issue is exactly what Week 3's golden-set harness exists to quantify and drive down — don't
  "fix" it further by guessing without eval numbers to check against.
- Windows console defaults stdout to cp1252; `Manifest.print_table()`/`.write()` explicitly force
  utf-8 because paper text routinely contains non-ASCII (math symbols, accented names, en-dashes).
  If you add another place that prints/writes paper-derived text on this machine, do the same.

Next up: Week 3 (golden set + eval harness) per plan.md §8 — hand-label 50 papers, build
extraction P/R + citation-faithfulness evals, iterate the prompt against real numbers instead of
one-off spot checks.
