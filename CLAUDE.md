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

# extract claims from ingested papers (the Week 2 exit test)
./.venv/Scripts/python.exe -m dissonance.extraction.run --limit 10

# claim review / golden-set labeling UI (web/README.md)
./.venv/Scripts/python.exe -m uvicorn web.app:app --reload   # http://127.0.0.1:8000/

# LLM-judge review pass (evals/llm_judge.py -- NOT human ground truth, see below)
./.venv/Scripts/python.exe -m evals.llm_judge --limit 250

# eval report: honest numbers (plan.md §5.2)
./.venv/Scripts/python.exe -m evals.report                   # or: make eval

# contradiction hunter: embedding blocking + cheap classifier -> suspected conflicts
./.venv/Scripts/python.exe -m dissonance.hunter.run --limit-pairs 200

# adjudicator: tiered verdict on each suspected conflict (the Week 4 exit test)
./.venv/Scripts/python.exe -m dissonance.adjudicator.run --limit 50

# supervisor stub demo (no-op pipeline, proves budgets/manifest work)
./.venv/Scripts/python.exe -m dissonance.supervisor.demo

# tests + lint
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check dissonance tests web evals
```

Note on `TemplateResponse`: the installed Starlette (1.3.1) requires
`templates.TemplateResponse(request, name, context)` -- `request` as an explicit first
positional argument, not just a `"request"` key inside `context`. The older
`TemplateResponse(name, {"request": request, ...})` call style silently produces a `TypeError:
unhashable type: 'dict'` deep in Jinja2's template cache, not an obvious error at the call site --
already fixed in `web/app.py`; don't reintroduce the old style if you add routes.

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

Week 3 (golden set + eval harness) is mostly built: `evals/report.py` (`python -m evals.report` or
`make eval`) prints the honest-numbers table, and the corpus is fully extracted (49/50 papers,
203 claims, $0.51 total). Real current numbers:
- **Citation faithfulness: 100%** (203/203) — the mechanical span-verification check works.
- **LLM-judge precision: 62%** (122 correct / 197 reviewed, 6 uncertain excluded) — see below,
  this is NOT the v1 target metric.
- **Human precision: N/A** — zero human labels exist yet. This is the actual gap.

**Important: there are two distinct review passes, never conflate them.**
- `web/` (the review UI) — a human clicks through and labels claims. `reviewer='human'` in
  `claim_labels`. This is plan.md §5.1's actual golden set.
- `evals/llm_judge.py` (`python -m evals.llm_judge --limit N`) — an LLM judge (currently
  `gpt-4.1`) reviews each claim against its verified source quote and labels it the same way.
  `reviewer='llm_judge:<model>'`. This is a disclosed, useful-but-non-authoritative signal, added
  because Claude was asked to do a review pass without a human available to do the real one. Every
  consumer (`LabelRepository.export_golden`, `.verdict_counts`, `.export_review_log`,
  `evals/report.py`) takes a `reviewer` filter and defaults to `'human'` where it matters (the
  golden-set export) specifically so LLM-judge output can never silently become "the golden set."
  The dashboard shows both counts side by side, never merged.
- 62% LLM-judge precision is real signal worth acting on even though it's not human-validated —
  spot-checking the "incorrect" verdicts via the review UI (`web/`) shows genuine extraction bugs
  (e.g. `direction` reversed relative to what the quote says). Worth fixing in the extraction
  prompt before or alongside the real human labeling pass.
- Recall is still N/A and stays N/A until someone (human) independently reads a paper and lists
  what claims SHOULD be there — neither review pass does that; both only triage what the
  extractor already produced.
- Known gotcha (fixed, but know why): both `dissonance/extraction/pipeline.py` and
  `evals/llm_judge.py` had the same bug where a transient network error fetching one paper's HTML
  crashed the entire batch. Fixed by catching fetch errors and leaving that unit for retry rather
  than crashing or recording a fake result. If you add a third place that fetches paper text in a
  loop, apply the same pattern.

Not yet built for Week 3: the actual human labeling pass (only you can do this), and
`evals/suites/` (Invarium integration, plan.md §5.3).

## Week 4 (contradiction hunter + adjudicator) — built, run against real data, exit test not met

`dissonance/hunter/` (embeddings, cheap-tier classifier, blocking via pgvector cosine similarity)
and `dissonance/adjudicator/` (tiered escalation, full-text context windows, typed verdicts, the
extraction_error re-queue loop) are both built and verified end-to-end. Real run: 172 cross-paper
candidate pairs from blocking → 4 flagged by the hunter's classifier → all 4 correctly adjudicated
as `conditional`/`scope_difference` (confidence 0.90-0.95) — the system correctly declined to
manufacture a false "genuine" verdict when the evidence didn't support one.

**plan.md's exit test (>=10 genuine conflicts) was NOT met — and the reason is upstream, not a
pipeline bug.** Max cross-paper claim-embedding similarity across the whole 203-claim corpus is
only 0.61 (measured directly via SQL, see docs/architecture.md's Week 4 section). The Week 1
`arxiv.scouts.run --query "LLM evaluation"` pulled a topically broad 50-paper sample — physics
(`New exact bispectrum shapes in multifield inflation`), GPU hardware, medical robotics, alongside
actual LLM-eval papers — not the tightly-scoped 300-500 paper corpus plan.md §2 specifies. There
just isn't enough genuine topical overlap in this corpus for real contradictions to exist in
volume. `configs/run.yaml`'s `hunter.min_similarity` is already tuned down to 0.45 to match what
this corpus actually contains (0.75 found zero candidates outright) — **don't tune it down
further to manufacture hits; that would just flag noise the classifier/adjudicator would (should)
reject.** The actual fix is re-scoping or expanding Week 1's ingestion query to a properly focused
LLM-evaluation corpus, then re-running hunter + adjudicator against it.

Other things worth knowing:
- `claims.embedding` (pgvector) needed `register_vector(conn)` wired into
  `dissonance/graph/db.py`'s `get_connection()` so Python lists round-trip as pgvector's `vector`
  type transparently — every repository method that touches `embedding` relies on this.
- `conflicts` has a unique index on `(claim_a, claim_b)` so re-running the hunter's blocking step
  is idempotent (`ON CONFLICT DO NOTHING`), and `ClaimRepository.find_candidate_pairs` excludes
  any pair already present in `conflicts` (any verdict) via `NOT EXISTS` — re-running
  `dissonance.hunter.run` after ingesting more papers only screens genuinely new pairs.
- Same fetch-failure class of bug (see Week 2/3 notes above) was proactively fixed in
  `dissonance/adjudicator/run.py`'s paper-text fetch before it could bite — same pattern, skip and
  retry later rather than crash or fake a result.

Next up: Week 5 (synthesis + living review + watcher) per plan.md §8 — though re-scoping the
corpus to actually hit the Week 4 exit test is arguably higher priority first.
