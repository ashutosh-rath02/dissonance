# Dissonance — A Multi-Agent Swarm for Detecting Contradictions in Scientific Literature

**One-liner:** Scite finds disagreements that authors already wrote down as citations. Dissonance finds the ones nobody has noticed yet — by extracting typed claims directly from full text, building a persistent claim graph, and running an adversarial adjudication loop over every suspected conflict.

**Why this project:** It exercises every discipline of modern agent engineering — multi-agent orchestration, parallel swarms, harness engineering, loop engineering, budget supervision — in a domain where ground truth is verifiable text, so every capability claim can be backed by a number.

---

## 1. Positioning (write this into the README on day one)

| System | What it does | What it misses |
|---|---|---|
| **Scite** | Classifies 1.2B+ citation statements as supporting / contrasting / mentioning | Only sees conflicts authors explicitly wrote as citations; papers that disagree but never cite each other are invisible |
| **Consensus** | Aggregate "agree/disagree" meter across studies | Vote-counting; no adjudication of *why* studies disagree, no scope/condition analysis |
| **Elicit** | Structured data extraction into per-query tables | Flat tables, not a persistent linked claim graph; no contradiction hunting |
| **LiRA / AutoSurvey / LatteReview** | Multi-agent review *writing* and screening | Automate synthesis, not conflict detection |
| **PaperQA / OpenScholar** | Citation-backed Q&A over papers | Answer questions; don't maintain a claim graph or detect inter-paper conflicts |
| **Dissonance** | Claim-level, citation-independent contradiction detection with typed adjudication and a living review | — |

**Defensible gap:** direct claim-vs-claim comparison + conflict typing (direct / conditional / methodological) + a living review over a persistent graph. No open-source system combines these.

---

## 2. Scope: the pilot domain

**Domain: LLM evaluation papers** (benchmarks, eval methods, contamination studies, judge reliability).

Why this niche:

- Contradiction-rich: benchmark results and eval-methodology claims conflict constantly.
- Self-referential flex: an agent system analyzing agent/LLM literature — interviewers can judge the output themselves without domain expertise.
- All papers are on arXiv → no paywall problems, clean LaTeX/HTML sources available for many.
- You can hand-label the golden set yourself in a weekend.

Hard scope rules:

- ONE domain until v1 ships. No "add biology later" until the harness numbers are published.
- Corpus cap for v1: ~300–500 papers. Big enough to find real conflicts, small enough to debug.
- English only. Full text where available; abstract-only papers get flagged, not silently degraded.

---

## 3. Architecture

### 3.1 Component map

```
Research question
      │
      ▼
┌─────────────┐
│ Query        │  decomposes question into search facets
│ Planner      │  (topics, synonyms, method filters, date ranges)
└─────┬───────┘
      ▼
┌──────────────────────────────┐
│ Scout Swarm (parallel)        │  arXiv API │ OpenAlex │ Semantic Scholar
│ + Screener (cheap model)      │  dedupe by DOI/arXiv ID, relevance filter
└─────┬────────────────────────┘
      ▼
┌──────────────────────────────┐
│ Extraction Swarm (parallel)   │  PDF/HTML → typed claims (schema below)
│ ↻ schema-invalid → retry      │  each claim stores its exact source span
└─────┬────────────────────────┘
      ▼
┌─────────────┐
│ Claim Graph  │  Postgres + pgvector; entity resolution, dedup,
│ (persistent) │  claim ↔ paper ↔ method ↔ population links
└─────┬───────┘
      ▼
┌──────────────────────────────┐
│ Contradiction Hunter          │  candidate pairs via embedding blocking
│                               │  + cheap classifier → suspected conflicts
└─────┬────────────────────────┘
      ▼
┌──────────────────────────────┐
│ Adjudicator Loop              │  pulls full-text context for both claims,
│ ↻ escalating model tiers      │  rules: genuine / scope-difference /
│ ↻ extraction-error → re-extract│  extraction-error, with typed verdict
└─────┬────────────────────────┘
      ▼
┌─────────────┐
│ Synthesis    │  living review page: consensus map, contradiction
│ Agent        │  table, per-claim confidence, full provenance
└─────────────┘
      ▲
      └── ↻ new-paper watcher triggers incremental re-run

Supervisor (cross-cutting): per-stage budgets, loop caps, kill-switch,
run manifest, tracing. Nothing runs outside the supervisor.
```

### 3.2 Claim schema (the core data structure)

```json
{
  "claim_id": "uuid",
  "paper_id": "arxiv:2501.01234",
  "assertion": "Few-shot prompting improves accuracy on GSM8K",
  "subject": "few-shot prompting",
  "object": "GSM8K accuracy",
  "direction": "increases | decreases | no_effect | mixed",
  "effect_size": {"value": 12.3, "unit": "pp", "reported": true},
  "conditions": {
    "model_class": "7B open-weight",
    "population_or_setting": "grade-school math",
    "other": ["temperature 0", "8 shots"]
  },
  "method_type": "benchmark_eval | ablation | rct | observational | theoretical | survey",
  "evidence_strength": "primary_result | secondary_result | cited_claim",
  "source_span": {"section": "5.2", "char_start": 14210, "char_end": 14390, "verbatim_hash": "sha256"},
  "extraction_confidence": 0.0,
  "extracted_by": {"model": "...", "prompt_version": "...", "run_id": "..."}
}
```

Design notes:

- `source_span` + `verbatim_hash` make citation-faithfulness checking mechanical: re-open the paper, check the span supports the assertion. This is the backbone of the eval harness.
- `conditions` is what lets the adjudicator distinguish a real contradiction from a scope difference.
- `extracted_by` provenance means every bad claim is traceable to a prompt version — you can bisect regressions.

### 3.3 Conflict record schema

```json
{
  "conflict_id": "uuid",
  "claim_a": "uuid", "claim_b": "uuid",
  "type": "direct | conditional | methodological | numerical",
  "verdict": "genuine | scope_difference | extraction_error | insufficient_context",
  "adjudicator_rationale": "text with quoted spans from both papers",
  "confidence": 0.0,
  "adjudication_cost_usd": 0.0,
  "loops_used": 1,
  "status": "open | resolved | escalated_to_human"
}
```

---

## 4. Loop engineering (make these explicit, they are interview material)

| Loop | Trigger | Policy | Cap |
|---|---|---|---|
| Extraction retry | JSON schema validation fails or span doesn't exist in source | Retry with validator error injected into prompt | 3 attempts, then quarantine paper |
| Extraction escalation | Cheap model confidence < threshold twice | Escalate to stronger model for that paper only | 1 escalation |
| Adjudication escalation | Cheap screen says "conflict" | Tier 2 model reads both full-text contexts | 2 tiers, then `insufficient_context` |
| Re-extraction loop | Adjudicator verdict = `extraction_error` | Claim deleted, paper re-queued for extraction with error note | 1 round trip; second failure → human queue |
| Identical-failure breaker | Same error signature 3× on same unit | Stop retrying, log signature, move on | hard |
| Incremental update | New-paper watcher finds papers | Only new papers extracted; hunter runs new-vs-existing pairs only | nightly batch |

Supervisor invariants (non-negotiable):

- Per-run USD budget; per-stage sub-budgets; the run halts gracefully at 90% and reports.
- Wall-clock cap per work unit; runaway units are killed, not awaited.
- Every run writes a manifest: papers touched, claims added, conflicts adjudicated, cost, loops-to-resolution histogram. The manifest is the demo.

---

## 5. Harness engineering (the crown jewel)

### 5.1 Golden set

- 50 hand-labeled papers from the pilot domain.
- Per paper: the claims a careful human would extract (aim ~5–10 each → ~300 golden claims).
- 20–30 hand-verified conflict pairs across the set, labeled with type and verdict, including at least 5 deliberate near-misses (scope differences that *look* like contradictions).
- Label format = same schemas as production. Store in `evals/golden/`.

### 5.2 Automated evals (run in CI on every prompt/pipeline change)

| Eval | Metric | v1 target |
|---|---|---|
| Claim extraction | precision / recall vs golden claims (fuzzy match on assertion + exact on direction) | P ≥ 0.85, R ≥ 0.70 |
| Citation faithfulness | % of claims whose stored span actually supports the assertion (LLM-judge + span check) | ≥ 0.95 |
| Contradiction detection | precision / recall on golden conflict pairs | P ≥ 0.80, R ≥ 0.60 |
| Adjudication verdict accuracy | agreement with human verdict on golden pairs | ≥ 0.80 |
| Cost & loops | $/paper extracted, $/conflict adjudicated, mean loops-to-resolution | track, publish honestly |

### 5.3 Invarium integration

- Wire the eval suite through Invarium as its flagship real-world case study.
- Write the "testing a multi-agent pipeline with Invarium" post — this fuses both portfolio pieces into one story.

Honesty rule: publish the real numbers, including failures. "Recall 0.61, here are the three failure modes" beats "state-of-the-art" every time.

---

## 6. Tech stack

| Layer | Choice | Rationale / fallback |
|---|---|---|
| Orchestration | LangGraph (or plain asyncio if you want to flex "no framework") | Pick one and defend it; document the tradeoff in the README |
| Models | Cheap tier for screening/extraction first pass; strong tier for adjudication + synthesis | Model-agnostic config; per-stage model selection is a talking point |
| Paper sources | arXiv API, OpenAlex, Semantic Scholar API | All free; rate-limit aware scouts |
| PDF → text | arXiv HTML/LaTeX source where available; **marker** or GROBID for PDF fallback | Budget real time here; this is the swamp |
| Storage | Postgres + pgvector (single instance, docker-compose) | Claims, papers, conflicts, embeddings in one place |
| Tracing | Langfuse (self-hosted or cloud free tier) | Every agent call traced with run_id |
| Config | Pydantic-settings + YAML per-stage configs (model, budget, caps, prompt version) | "Proper setup" made visible |
| Frontend | Static site or small FastAPI + HTMX/React page for the living review | Contradiction table is the hero view |
| CI | GitHub Actions: lint, unit tests, eval suite on golden set (cheap-model mode) | Evals in CI = harness engineering receipt |

---

## 7. Repo structure

```
dissonance/
├── README.md                  # positioning table, demo GIF, honest numbers
├── docker-compose.yml         # postgres+pgvector, langfuse
├── configs/
│   ├── run.yaml               # budgets, caps, model tiers per stage
│   └── prompts/               # versioned prompt files (v1.md, v2.md ...)
├── dissonance/
│   ├── supervisor/            # budgets, loop caps, manifests, kill-switch
│   ├── planner/
│   ├── scouts/                # arxiv.py, openalex.py, semanticscholar.py
│   ├── screener/
│   ├── extraction/            # parser adapters + claim extractor + validator
│   ├── graph/                 # models, entity resolution, dedup
│   ├── hunter/                # blocking + candidate classifier
│   ├── adjudicator/           # tiered adjudication loop
│   ├── synthesis/             # living review generator
│   └── watcher/               # incremental update trigger
├── evals/
│   ├── golden/                # labeled papers, claims, conflict pairs
│   ├── suites/                # invarium test suites
│   └── report.py              # prints the honest-numbers table
├── web/                       # living review UI
├── tests/                     # unit tests (deterministic, no LLM calls)
└── docs/
    ├── architecture.md
    ├── decisions/             # ADRs: why LangGraph, why pgvector, etc.
    └── benchmark.md           # published results
```

---

## 8. Milestones (6 weeks, ~10–15 h/week solo)

### Week 1 — Skeleton + ingestion
- Repo, docker-compose, configs, supervisor stub (budgets + manifest from day one, even if trivial).
- Scouts for arXiv + OpenAlex; screener; dedupe; land ~300 papers' metadata for the pilot domain.
- Parser adapter: arXiv HTML/LaTeX path working; PDF fallback stubbed.
- **Exit test:** one command ingests the corpus and prints a manifest with counts and cost.

### Week 2 — Extraction swarm + claim graph
- Claim schema, extractor prompt v1, JSON validation + retry loop, span verification.
- Postgres models, entity resolution v1 (normalize benchmark/model/method names), dedup.
- **Exit test:** 50 papers → claims in graph; spot-check 20 claims by hand; measure rough precision.

### Week 3 — Golden set + eval harness  ← do NOT skip to the fun part
- Hand-label the 50-paper golden set (yes, the boring weekend).
- Eval suite: extraction P/R, citation faithfulness. Wire into Invarium + CI.
- Iterate extractor prompts against the harness until v1 targets are hit or honestly missed.
- **Exit test:** `make eval` prints the metrics table; CI runs it.

### Week 4 — Contradiction hunter + adjudicator
- Embedding blocking (same subject/object neighborhood) → cheap pair classifier → suspect queue.
- Tiered adjudicator with full-text context retrieval; conflict records with rationale; re-extraction loop.
- Label golden conflict pairs; add hunter/adjudicator evals to the suite.
- **Exit test:** end-to-end run finds ≥ 10 genuine conflicts in the corpus with rationales you agree with.

### Week 5 — Synthesis + living review + watcher
- Living review generator: consensus map per sub-question, contradiction table with quoted spans, confidence per claim.
- Watcher: nightly arXiv poll → incremental pipeline → review updates with a changelog.
- Web UI: the contradiction table is the hero; every cell links to the exact source spans.
- Human escalation queue: simple view listing `escalated_to_human` conflicts with both spans side-by-side and an approve/override action that writes back to the graph.
- Replay: persist every agent call's inputs/outputs keyed by run_id (via Langfuse traces + local cache) so any run can be re-executed deterministically without new LLM calls — this is also how you debug adjudication regressions cheaply.
- **Exit test:** publish the living review for the pilot domain at a public URL; replay a full prior run offline.

### Week 6 — Benchmark, polish, publish
- Full-corpus run; record the manifest (cost, loops, counts) as the published benchmark.
- README with positioning table, architecture diagram, honest-numbers table, 2-min demo video.
- Blog post #1: "Finding contradictions Scite can't see" (the system).
- Blog post #2: "Evals for a multi-agent pipeline with Invarium" (the harness).
- **Exit test:** a stranger can docker-compose up, run against 10 papers, and reproduce a mini-review.

Stretch (post-v1, only after publishing): second domain (e.g., sleep/caffeine studies) to prove domain transfer; human-in-the-loop conflict resolution queue; PDF-heavy domain to battle-test GROBID path.

---

## 9. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| PDF parsing swamp eats weeks | High | Pilot domain chosen for arXiv HTML/LaTeX availability; PDF path is fallback, not critical path |
| Contradiction false-positive flood | High | That's the *point* of the adjudicator loop; near-miss golden pairs keep you honest |
| Entity resolution rabbit hole | Medium | v1 = normalization tables + embedding similarity; log unresolved, don't chase perfection |
| Cost blowout on adjudication | Medium | Tiered models + per-stage budgets + blocking before classification |
| "Isn't this just Scite?" | Certain (someone will ask) | Positioning table in README; demo a conflict between two papers that never cite each other |
| Scope creep to more domains | High (it's you) | Hard rule in §2; the harness numbers ship before any expansion |
| Golden-set labeling fatigue | Medium | 50 papers max; label claims only for sections the extractor targets (abstract, results, conclusion) |

---

## 10. Interview talking points this project buys you

1. **Why multi-agent?** Parallel scouts/extractors are embarrassingly parallel; hunter/adjudicator need different context windows and model tiers; a single agent cannot hold 300 papers. You can argue this concretely, not ideologically.
2. **Loop engineering:** retry-with-validator-feedback, tiered escalation, circuit breakers, re-extraction round trips — each with caps and observed loops-to-resolution stats.
3. **Harness engineering:** golden set, five automated evals in CI, citation-faithfulness checking via stored spans, prompt-version bisection of regressions.
4. **Orchestration:** planner/fan-out/merge, budget supervision, incremental re-runs, run manifests, deterministic replay from traces.
5. **Judgment:** you scoped to one domain, published honest numbers including failures, and wrote ADRs for every major choice.

---

## 11. First session checklist (do today)

- [ ] Create repo `dissonance` (or your name of choice), MIT license, README with the one-liner + positioning table
- [ ] docker-compose: postgres + pgvector up
- [ ] `configs/run.yaml` with budget/caps skeleton
- [ ] Supervisor stub that wraps a no-op pipeline and prints a manifest
- [ ] arXiv scout: fetch 50 papers for "LLM evaluation" query, store metadata
- [ ] Commit. Momentum beats perfection.