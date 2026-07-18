# Dissonance

**Scite finds disagreements that authors already wrote down as citations. Dissonance finds the ones nobody has noticed yet** — by extracting typed claims directly from full text, building a persistent claim graph, and running an adversarial adjudication loop over every suspected conflict.

Status: **Week 5 — living review, deployed.** Weeks 1–4 (skeleton, ingestion, extraction, eval harness, hunter + adjudicator) are done and independently verified. Real numbers below; see [Honesty rule](#honesty-rule) for the full story, including a schema bug that was making the adjudicator report false positives.

**Live demo:** http://3.220.187.89:8000/review — browse all 1553 adjudicated conflicts, filter by verdict, drill into any conflict to see both claims' quotes re-verified live against the source paper. Read-only; no API key required.

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

- Corpus cap for v1: ~300–500 papers. Current: **467 papers, 1811 claims** (see `dissonance/scouts/run.py`'s query presets).
- English only; full text where available, abstract-only papers flagged not degraded.

## Architecture

```
Research question → Query Planner → Scout Swarm (arXiv/OpenAlex/Semantic Scholar)
  → Extraction Swarm (typed claims) → Claim Graph (Postgres+pgvector)
  → Contradiction Hunter (embedding blocking + cheap classifier)
  → Adjudicator Loop (tiered, full-text context) → Synthesis (living review)
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
python -m dissonance.scouts.run --limit 250         # field-scoped query, see dissonance/scouts/run.py
python -m dissonance.extraction.run --limit 250 --workers 8
python -m dissonance.hunter.run --limit-pairs 500 --workers 10
python -m dissonance.adjudicator.run --limit 500 --workers 10
python -m evals.report                              # or: make eval
```

Each command prints a manifest: units touched, claims/conflicts found, cost, wall-clock time.

## Deployment

Live at http://3.220.187.89:8000/review, running on a single EC2 instance (t3.large) via Docker Compose:

```bash
# on the host, with .pem key + repo checked out
docker compose up -d --build      # builds web image, starts db + web
```

- `Dockerfile` builds the web app image; `docker-compose.yml`'s `web` service points it at the `db`
  service on the internal Docker network (see the compose file's comments).
- The web app never calls an LLM (read/write Postgres + re-fetch arXiv text only), so the
  container needs no `OPENAI_API_KEY`.
- The instance's security group allows inbound TCP 8000 from anywhere; everything else (ingestion,
  extraction, hunting, adjudication) still runs locally against the same Postgres instance's data,
  which was migrated to the EC2 Postgres container via `pg_dump`/`pg_restore`.
- No custom domain or TLS yet -- plain HTTP on the instance's Elastic IP.

## Repo layout

See [docs/architecture.md](docs/architecture.md) for the annotated tree.

## Honesty rule

We publish real eval numbers, including failures. Current numbers (`python -m evals.report`, full corpus: 467 papers, 1811 claims, run against `gpt-4.1`/`gpt-4.1-mini` -- see [ADR 0004](docs/decisions/0004-gpt-4.1-standin-for-gpt-5.md)):

| Eval | v1 target | Current |
|---|---|---|
| Citation faithfulness (mechanical, all 1811 claims) | ≥95% | **100%** |
| Claim extraction precision, LLM-judge (disclosed, *not* the v1 metric) | — | **78%** (1405/1799 reviewed) |
| Claim extraction precision, human (the actual v1 metric, plan.md §5.1) | ≥85% | **N/A — no human labels yet** |
| Claim extraction recall | ≥70% | **N/A** — requires independent human claim enumeration per paper, not built |
| Contradiction detection: genuine conflicts found | ≥10 (plan.md's exit test) | **0**, verified by hand — see below |

Total cost so far: ~$8 across ingestion, extraction (453 papers), embeddings, hunter screening (3672 candidate pairs), and adjudication (1553 pairs).

The LLM-judge number is a disclosed, useful-but-non-authoritative signal (see `evals/llm_judge.py`), never conflated with human ground truth in code or reporting. It rose from an initial 62% to 78% after fixing the schema bug described below, which affected this pipeline too.

### Why the hunter/adjudicator found 0 genuine conflicts, verified by hand

Two separate things happened here, and both are worth knowing before touching this code.

**First, the corpus was re-scoped.** The original Week 1 query (`all:"LLM evaluation"`, sorted by
submission date) pulled a topically broad 50-paper sample — physics, GPU hardware, medical
robotics alongside actual LLM-eval papers — where max cross-paper claim-embedding similarity
topped out at 0.61. Rebuilt the query to be field-scoped and category-restricted
(`cat:cs.CL AND abs:"language model" AND (abs:evaluation OR abs:benchmark OR ...)`, relevance-sorted),
added a second preset targeting foundational/famous papers by title (MMLU, HellaSwag, Chatbot
Arena, GSM8K, etc. — the papers later work actually argues with), and grew the corpus to 467
papers / 1811 claims. This alone took candidate pairs from 4 to 1552.

**Second — and this is the more important finding — a schema bug was making the adjudicator
report false positives, and fixing it dropped "genuine" conflicts from a peak of 15 down to 0.**
`AdjudicatorVerdict` originally declared `verdict` before `rationale`. OpenAI's structured outputs
fill JSON fields in schema declaration order, so the model was committing to a verdict *before*
writing the reasoning meant to justify it — and the two could end up contradicting each other.
Caught by manually reading the top-confidence "genuine" verdicts from a real run: multiple
rationales explicitly concluded "there is no contradiction" / "these are compatible perspectives"
while their own verdict field said `genuine`.

Fixing the field order (reasoning before answer) helped a lot but didn't fully close it, so a
second, independent safety net was added: a keyword-based consistency checker
(`dissonance/adjudicator/consistency.py`) that catches a self-contradictory "genuine" verdict and
forces it to escalate to a stronger model tier, or fall back to `insufficient_context` if it
recurs. Verifying *that* checker against real output took **five separate rounds** — each fresh
adjudication run surfaced a phrasing the checker's regex didn't cover yet ("no contradiction"
bare, "not a genuine contradiction", "without contradicting each other", "no evident
contradiction", "rather than a direct contradiction" in noun form). After round five, one
remaining false positive was corrected by hand rather than chasing a sixth phrasing — the honest
engineering conclusion, documented in that file, is that the checker narrows the pool of verdicts
worth reading, it does not prove them. Every "genuine" verdict should still be read by a human
before being trusted.

**The fully-verified result, after all of that: 0 genuine conflicts across 1553 adjudicated
candidate pairs.** The adjudicator's `scope_difference` rationales are, on inspection, genuinely
well-reasoned — real disagreements in this corpus keep turning out to be explainable by different
models, datasets, or methodology once read carefully. That may be a property of the corpus (not
narrow enough to catch papers running near-identical experiments), a property of the literature
(real head-to-head contradictions under truly comparable conditions may just be rarer than
assumed), or both. Either way: this is the honest number, arrived at by verification rather than
by trusting model output, which is the whole point of this project.

## License

MIT — see [LICENSE](LICENSE).
