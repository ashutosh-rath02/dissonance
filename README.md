# Dissonance

**Scite finds disagreements that authors already wrote down as citations. Dissonance finds the ones nobody has noticed yet** — by extracting typed claims directly from full text, building a persistent claim graph, and running an adversarial adjudication loop over every suspected conflict.

Status: **Week 3 — golden set + eval harness.** Weeks 1–2 (skeleton, ingestion, extraction) are done and verified against real papers. Real numbers below; see [Honesty rule](#honesty-rule).

## Positioning

| System | What it does | What it misses |
|---|---|---|
| **Scite** | Classifies 1.2B+ citation statements as supporting / contrasting / mentioning | Only sees conflicts authors explicitly wrote as citations; papers that disagree but never cite each other are invisible |
| **Consensus** | Aggregate "agree/disagree" meter across studies | Vote-counting; no adjudication of *why* studies disagree, no scope/condition analysis |
| **Elicit** | Structured data extraction into per-query tables | Flat tables, not a persistent linked claim graph; no contradiction hunting |
| **LiRA / AutoSurvey / LatteReview** | Multi-agent review *writing* and screening | Automate synthesis, not conflict detection |
| **PaperQA / OpenScholar** | Citation-backed Q&A over papers | Answer questions; don't maintain a claim graph or detect inter-paper conflicts |
| **Dissonance** | Claim-level, citation-independent contradiction detection with typed adjudication and a living review | — |

**Defensible gap:** direct claim-vs-claim comparison + conflict typing (direct / conditional / methodological) + a living review over a persistent graph.

## Pilot domain

LLM evaluation papers (benchmarks, eval methods, contamination studies, judge reliability) on arXiv. See [docs/architecture.md](docs/architecture.md) for the full scope rationale and [plan.md](plan.md) for the original design doc.

- Corpus cap for v1: ~300–500 papers.
- English only; full text where available, abstract-only papers flagged not degraded.

## Architecture

```
Research question → Query Planner → Scout Swarm (arXiv/OpenAlex/Semantic Scholar)
  → Extraction Swarm (typed claims) → Claim Graph (Postgres+pgvector)
  → Contradiction Hunter → Adjudicator Loop (tiered) → Synthesis (living review)
```

A cross-cutting **Supervisor** enforces per-stage budgets, loop caps, and writes a run manifest for every run. Nothing runs outside the supervisor. Full diagram in [docs/architecture.md](docs/architecture.md).

## Tech stack

- **Orchestration:** plain asyncio, no framework — see [docs/decisions/0001-orchestration.md](docs/decisions/0001-orchestration.md) for why.
- **Models:** OpenAI, cheap tier for screening/extraction, strong tier for adjudication/synthesis, per-stage config (model-agnostic interface).
- **Storage:** Postgres + pgvector, single docker-compose instance.
- **Sources:** arXiv API, OpenAlex, Semantic Scholar (free, rate-limit aware).

## Quickstart

```bash
cp .env.example .env               # fill in OPENAI_API_KEY
docker compose up -d db            # postgres + pgvector
python -m venv .venv && .venv/Scripts/activate   # or source .venv/bin/activate
pip install -e ".[dev]"
python -m dissonance.graph.migrate                 # create schema
python -m dissonance.scouts.run --query "LLM evaluation" --limit 50
```

The scout run prints a manifest: papers found, papers stored, cost, wall-clock time.

## Repo layout

See [docs/architecture.md](docs/architecture.md) for the annotated tree.

## Honesty rule

We publish real eval numbers, including failures. Current numbers (`python -m evals.report`, corpus: 49/50 papers extracted, 203 claims, run against `gpt-4.1`/`gpt-4.1-mini` -- see [ADR 0004](docs/decisions/0004-gpt-4.1-standin-for-gpt-5.md)):

| Eval | v1 target | Current |
|---|---|---|
| Citation faithfulness (mechanical, all 203 claims) | ≥95% | **100%** |
| Claim extraction precision, LLM-judge (disclosed, *not* the v1 metric) | — | **62%** (122/197 reviewed) |
| Claim extraction precision, human (the actual v1 metric, plan.md §5.1) | ≥85% | **N/A — no human labels yet** |
| Claim extraction recall | ≥70% | **N/A** — requires independent human claim enumeration per paper, not built |
| Contradiction detection / adjudication accuracy | — | **N/A** — hunter/adjudicator are Week 4 |

The LLM-judge number is a disclosed, useful-but-non-authoritative signal (see `evals/llm_judge.py`), never conflated with human ground truth in code or reporting. Spot-checking its "incorrect" verdicts through the review UI (`web/`) surfaces real extraction bugs (e.g. `direction` reversed relative to the source quote) worth fixing regardless of who validates it.

## License

MIT — see [LICENSE](LICENSE).
