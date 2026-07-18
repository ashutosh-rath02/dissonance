# Dissonance

Automated contradiction detection for AI research papers — Dissonance reads papers, extracts
factual claims, and flags pairs of claims across different papers that actually disagree with
each other.

**Live demo:** http://3.220.187.89:8000/review — browse 1553 adjudicated conflicts, filter by
verdict, drill into any conflict to see both claims' quotes re-verified live against the source
paper. Read-only, no login required.

## What problem does this solve?

AI researchers publish hundreds of papers evaluating language models — claims like *"model X
scores 84% on benchmark Y"* or *"chain-of-thought prompting improves reasoning by 15%."*
Different papers sometimes quietly contradict each other, but nobody notices, because the papers
never cite one another or phrase things the same way. Existing tools (Scite, Consensus) only catch
disagreements authors already flagged via citation — if two papers never reference each other,
the disagreement is invisible to them.

Dissonance instead compares the *claims themselves*, independent of citations:

1. **Read papers** and pull out every factual claim as structured data — subject, object,
   direction, effect size, conditions — not just a summary paragraph.
2. **Find claims that are about the same thing**, across different papers, using embedding
   similarity (nothing pairwise-compares all claims against all others — that doesn't scale).
3. **Ask an AI adjudicator to actually think about each pair**: is this a genuine contradiction,
   or does it just look like one because the papers tested different models, datasets, or setups?
4. **Publish every verdict**, with the adjudicator's reasoning and a link back to the exact
   sentence it came from in each paper — re-verified against the source on every page load, never
   just trusted.

The output is a browsable table anyone can audit: not "these papers disagree" as an opaque score,
but the specific claims, the specific quotes, and the specific reasoning.

## How it works

```
arXiv papers → Extraction (typed claims) → Claim Graph (Postgres + pgvector)
  → Contradiction Hunter (embedding similarity + cheap classifier narrows candidates)
  → Adjudicator (stronger model reads full-text context, issues a typed verdict)
  → Living Review (public, browsable, every quote re-verified live)
```

A cross-cutting **Supervisor** wraps every stage: it enforces per-stage cost budgets, wall-clock
caps, and retry/escalation limits, and writes a manifest of what happened on every run. Full
diagram and code layout: [docs/architecture.md](docs/architecture.md). Full design rationale:
[plan.md](plan.md).

## AI engineering principles this project leans on

Building a pipeline where an LLM's output feeds into another LLM's decision, several times over,
surfaces failure modes that don't show up in a single prompt-response demo. What actually mattered
here:

- **Don't trust the model where you can check mechanically.** A claim's source quote is never
  stored — only a character offset and a SHA-256 hash. The web UI re-fetches the paper and
  re-slices the span on every page load, so "the quote matches the paper" is a fact you can verify,
  not a claim you have to believe. This caught real extraction bugs a plausibility check would have
  missed.
- **Field order in structured outputs is not cosmetic.** OpenAI's structured outputs fill JSON
  fields in schema declaration order. Early on, the adjudicator's schema asked for `verdict` before
  `rationale` — so the model committed to an answer *before* writing the reasoning meant to justify
  it, and the two would sometimes contradict each other. Reordering every verdict schema to put
  reasoning first (and re-measuring) took LLM-judge precision from 62% to 78%. See the Week 4
  section of [CLAUDE.md](CLAUDE.md) for the full story.
- **A single verification layer isn't enough — add an independent safety net.** Fixing the field
  order reduced self-contradictory "genuine" verdicts a lot but not to zero. A second, independent
  consistency checker (`dissonance/adjudicator/consistency.py`) scans the rationale text for
  language that contradicts the verdict and forces a re-check rather than trusting a single pass.
- **Retrieve before you generate.** Comparing every claim against every other claim is
  quadratic and mostly wasted LLM calls on unrelated pairs. Embedding similarity narrows ~1811
  claims down to a few thousand plausible candidate pairs before any expensive adjudication call
  runs — the same "retrieve, then reason" shape as RAG, applied to pairwise comparison instead of
  question answering.
- **Escalate, don't over-provision.** The adjudicator starts with a cheaper model tier and only
  escalates to a stronger one when confidence is low or the consistency check fails — most pairs
  never need the expensive model.
- **Budgets and loop caps are infrastructure, not an afterthought.** Every pipeline stage runs
  inside a `Supervisor` context that enforces cost ceilings, wall-clock limits, and retry caps
  centrally (`dissonance/supervisor/core.py`), so a runaway loop in one stage can't silently burn
  the whole budget. Config-driven (`configs/run.yaml`), not hardcoded per stage.
- **Keep human and AI evaluation signals structurally separate.** The database schema tags every
  label with who produced it (`reviewer='human'` vs `reviewer='llm_judge:<model>'`), and every
  consumer of labels defaults to the human-only filter. This makes it structurally impossible for
  an LLM's self-assessment to quietly become the reported "ground truth" number.
- **Report the number you got, not the number you wanted.** The adjudicator's exit test
  (≥10 genuine conflicts) was not met — the honest result after full verification is 0. That's
  published as-is below, with the reasoning for why, rather than loosening the verification to
  manufacture a hit.
- **Isolate failures per unit of work.** Early versions of the extraction, hunting, adjudication,
  and eval-report loops all shared one bug: a single paper's transient fetch error crashed the
  entire batch. Every fetch loop now catches that error and leaves just that one unit pending for
  retry.

## Try it locally

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
python -m uvicorn web.app:app --reload              # browse at http://127.0.0.1:8000/review
python -m evals.report                              # or: make eval
```

Each pipeline command prints a manifest: units touched, claims/conflicts found, cost, wall-clock
time.

## Deployment

Live at http://3.220.187.89:8000/review, running on a single EC2 instance via Docker Compose:

```bash
docker compose up -d --build      # builds the web image, starts db + web
```

`Dockerfile` builds the web app; `docker-compose.yml`'s `web` service points it at the `db`
service over the internal Docker network. The web app never calls an LLM (it only reads/writes
Postgres and re-fetches paper text from arXiv for live quote verification), so the container needs
no `OPENAI_API_KEY`.

## Honesty rule

We publish real eval numbers, including the ones that didn't land where we hoped. Current numbers
(`python -m evals.report`, full corpus: 467 papers, 1811 claims):

| Eval | v1 target | Current |
|---|---|---|
| Citation faithfulness (mechanical, all 1811 claims) | ≥95% | **100%** |
| Claim extraction precision, LLM-judge (disclosed, *not* the v1 metric) | — | **78%** (1405/1799 reviewed) |
| Claim extraction precision, human (the actual v1 metric) | ≥85% | **N/A — no human labels yet** |
| Claim extraction recall | ≥70% | **N/A** — requires independent human claim enumeration, not built |
| Contradiction detection: genuine conflicts found | ≥10 (exit test) | **0**, verified by hand |

Total cost so far: ~$8 across ingestion, extraction, embeddings, hunter screening, and
adjudication.

**Why 0 genuine conflicts, and why that's a trustworthy number and not a bug:** two things
happened. First, the corpus was re-scoped from a topically broad 50-paper sample to a
field-restricted, relevance-sorted 467-paper corpus, which alone took candidate pairs from 4 to
1552. Second, a schema-ordering bug (above) was initially producing false "genuine" verdicts —
after fixing it and adding an independent consistency check, every remaining "genuine" candidate
turned out, on manual reading, to be a well-explained scope or methodology difference rather than
a real contradiction. The full investigation — including five rounds of tightening the consistency
checker against real model output — is documented in the Week 4 section of
[CLAUDE.md](CLAUDE.md). 0 confirmed genuine conflicts, arrived at through verification rather than
by trusting model output, is itself the point of this project.

## Repo layout

See [docs/architecture.md](docs/architecture.md) for the annotated tree.

## License

MIT — see [LICENSE](LICENSE).
