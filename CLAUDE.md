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
`make eval`) prints the honest-numbers table. Numbers below are from the full corpus after Week 4's
re-scoping (see that section) -- 467 papers, 1811 claims:
- **Citation faithfulness: 100%** (1811/1811) — the mechanical span-verification check works.
- **LLM-judge precision: 78%** (1405 correct / 1799 reviewed, 12 uncertain excluded) — up from an
  initial 62% (197 reviewed) after fixing the verdict-before-rationale schema bug described in the
  Week 4 section below, which affected this pipeline too.
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
- 78% LLM-judge precision is real signal worth acting on even though it's not human-validated —
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

## Week 4 (contradiction hunter + adjudicator) — done, independently verified, exit test not met

`dissonance/hunter/` (embeddings, cheap-tier classifier, blocking via pgvector cosine similarity)
and `dissonance/adjudicator/` (tiered escalation, full-text context windows, typed verdicts, the
extraction_error re-queue loop) are both built. Corpus grew from 50 to **467 papers / 1811
claims** (see "corpus re-scoping" below). Final verified result: **1553 candidate pairs
adjudicated, 0 confirmed genuine conflicts.** plan.md's exit test (≥10) was not met. Read the rest
of this section before assuming that's a simple fix or a simple bug — it's neither.

### Corpus re-scoping (Week 1 revisited)

The original `arxiv.scouts.run --query "LLM evaluation"` (loose `all:` match, sorted by submission
date) pulled a topically broad 50-paper sample — physics, GPU hardware, medical robotics alongside
actual LLM-eval papers. Max cross-paper claim-embedding similarity topped out at 0.61, so
`hunter.min_similarity` (`configs/run.yaml`) had to be tuned down from 0.75 (zero candidates) to
0.45 just to get anything through blocking. Fixed at the source: `dissonance/scouts/run.py` now
defaults to a field-scoped, relevance-sorted query (`cat:cs.CL AND abs:"language model" AND
(abs:evaluation OR abs:benchmark OR ...)`, see `DEFAULT_QUERY`), plus a `--preset famous` query
scoped to foundational papers by title (MMLU, HellaSwag, Chatbot Arena, GSM8K, etc. — the papers
later work actually argues with). This alone took candidate pairs from 4 to 1552 — corpus scoping
was the real lever, not adjudicator tuning.

### Concurrency

`dissonance/extraction/run.py`, `dissonance/hunter/run.py`, `dissonance/adjudicator/run.py`, and
`evals/llm_judge.py` all now run their work across a `ThreadPoolExecutor` (default 8-15 workers) —
sequential extraction alone would have taken hours against 400+ pending papers. This required
making `Supervisor` thread-safe (`dissonance/supervisor/core.py` — `spend`/`increment`/`note`/
`record_loops_to_resolution` all take an internal lock; `budget.halted` is read lock-free by
design, since a one-tick-stale read just means a small, acceptable overshoot). Each worker still
opens its own DB connection per unit of work (psycopg connections aren't meant to be shared across
threads) — that part of the design was already connection-per-paper before concurrency, so it
translated directly. `evals/report.py`'s citation-faithfulness fetch loop was the last sequential
one; parallelized last, after it crashed running against the full 467-paper corpus (see next
section — every fetch loop in this codebase needs the same try/except pattern, and this one didn't
have it yet).

### The transient-fetch-crash pattern (recurring — check every new fetch loop)

Four separate places had the same bug: a transient DNS/network error fetching one paper's HTML
crashed the *entire* batch, losing progress on everything queued after it.
`dissonance/extraction/pipeline.py`, `dissonance/adjudicator/run.py`, `evals/llm_judge.py`, and
`evals/report.py` all needed a `try/except` around `fetch_full_text` that leaves the affected
unit `pending` (or skips it for this run) rather than crashing or recording a fake result. If you
add a fifth place that fetches paper text in a loop, apply the same pattern from the start.

### The verdict-before-rationale schema bug — the important one

`AdjudicatorVerdict` (`dissonance/adjudicator/schema.py`) originally declared `verdict` before
`rationale`. OpenAI structured outputs fill JSON fields in schema declaration order, so the model
was committing to a verdict *before* writing the reasoning meant to justify it. Caught by manually
reading the top-confidence "genuine" verdicts from a real run: several rationales explicitly
concluded "there is no contradiction" while their own verdict field said `genuine`. This inflated
an early run to 15 "genuine" conflicts, of which 4 of the top 5 were self-contradictory by this
measure.

**Fix 1 (schema field order):** put `rationale` first (reasoning before answer). Also applied to
`HunterScreen` (`dissonance/hunter/schema.py`) and `JudgeVerdict` (`evals/judge_schema.py`) — same
bug, same fix. `evals/llm_judge.py`'s Week 3 precision number was re-measured after this fix: 62%
→ 78%, on a larger sample (197 → 1799 reviewed). Also applied preventively to
`ExtractedClaim` (`dissonance/extraction/schema.py`, `quote` before `assertion`) though no bug was
caught there — same principle, no demonstrated failure.

**Fix 1 alone wasn't enough.** It cut the self-contradiction rate a lot but didn't eliminate it —
still stochastic. Added a second, independent safety net:
`dissonance/adjudicator/consistency.py`'s `rationale_contradicts_verdict()`, a keyword/regex check
that catches a self-contradictory "genuine" verdict and forces it back into the tiered-escalation
loop (retry at the next tier, or fall back to `insufficient_context` if it recurs at the last
tier). **Getting this checker actually correct took five rounds** — each fresh adjudication run
surfaced a phrasing the regex didn't cover: "no contradiction" (bare, no adjective), "not a
genuine contradiction" (a regex alternation bug — `(?:genuine|real )?` only puts the trailing
space on the *last* alternative, so `"genuine"` alone never matched), "without contradicting each
other", "no evident contradiction", "rather than a direct contradiction" (noun form vs. the gerund
the pattern covered). After round five, the one remaining false positive was corrected by hand in
the database rather than chasing a sixth phrasing.

**The honest conclusion, documented in `consistency.py`'s docstring: this heuristic narrows the
pool of "genuine" verdicts worth reading, it does not prove them.** Manually read every "genuine"
verdict this pipeline produces before trusting it — it is not mechanically verified the way
citation faithfulness (source-span hashes) is elsewhere in this codebase. If you re-run the
adjudicator and see a "genuine" verdict, read its rationale before believing it.

### What the final 0-genuine result actually means

After both fixes, the adjudicator's `scope_difference` rationales read as genuinely well-reasoned
on inspection — real disagreements in this corpus keep turning out to be explainable by different
models, datasets, or methodology once read carefully. Don't read "0 genuine conflicts" as "the
adjudicator is broken" or loosen its confidence bar / the consistency checker to manufacture hits
— both would reintroduce exactly the bug that was just fixed. If you want to hit the exit test
honestly, the lever is corpus scoping (narrower sub-topic, more papers running near-identical
experiments), not adjudicator calibration.

### Other things worth knowing

- `claims.embedding` (pgvector) needed `register_vector(conn)` wired into
  `dissonance/graph/db.py`'s `get_connection()` so Python lists round-trip as pgvector's `vector`
  type transparently. This has to be **best-effort** (wrapped in try/except): `register_vector`
  itself requires the `vector` extension to already exist, but `migrate.py`'s first connection is
  what *creates* that extension — a chicken-and-egg failure invisible locally (dev DB already had
  it) but immediate in CI against a fresh database. Verify any change here against a genuinely
  fresh Postgres container, not just a re-run against an already-migrated one.
- `conflicts` has a unique index on `(claim_a, claim_b)`, and a separate `hunter_screened_pairs`
  table (not `conflicts` — a hunter rejection isn't a Conflict verdict per plan.md's schema) tracks
  every pair the classifier has looked at regardless of verdict, so re-running
  `dissonance.hunter.run` only screens genuinely new pairs.

Next up: Week 5 (synthesis + living review + watcher) per plan.md §8. Corpus re-scoping already
happened once (50 → 467 papers) and still landed at 0 genuine conflicts after full verification —
if the exit test literally matters, the next lever is a narrower sub-topic (papers more likely to
run near-identical experiments against each other), not another broad re-scope. But 0 confirmed,
rigorously-verified genuine conflicts is itself a defensible, honestly-reported result; don't feel
obligated to keep re-scoping until a number appears.
