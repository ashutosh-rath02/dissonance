-- Dissonance claim graph schema. Applied by `python -m dissonance.graph.migrate`.

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS papers (
    paper_id            TEXT PRIMARY KEY,          -- e.g. 'arxiv:2501.01234'
    arxiv_id             TEXT UNIQUE,
    doi                  TEXT,
    title                TEXT NOT NULL,
    abstract             TEXT,
    authors              TEXT[] NOT NULL DEFAULT '{}',
    published_at         TIMESTAMPTZ,
    updated_at           TIMESTAMPTZ,
    primary_category     TEXT,
    categories           TEXT[] NOT NULL DEFAULT '{}',
    pdf_url              TEXT,
    html_url             TEXT,
    source               TEXT NOT NULL,             -- 'arxiv' | 'openalex' | 'semanticscholar'
    full_text_status      TEXT NOT NULL DEFAULT 'unknown',  -- html_available | pdf_only | abstract_only | unknown
    ingested_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 'pending' | 'done' | 'quarantined' (schema-invalid extraction exhausted its
-- retries, see plan.md §4's extraction retry loop). Added via ALTER so
-- re-running migrate.py against an already-applied schema still works.
ALTER TABLE papers ADD COLUMN IF NOT EXISTS extraction_status TEXT NOT NULL DEFAULT 'pending';

CREATE TABLE IF NOT EXISTS claims (
    claim_id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    paper_id             TEXT NOT NULL REFERENCES papers(paper_id) ON DELETE CASCADE,
    assertion            TEXT NOT NULL,
    subject              TEXT,
    object                TEXT,
    direction            TEXT,                      -- increases | decreases | no_effect | mixed
    effect_size          JSONB,
    conditions           JSONB,
    method_type          TEXT,
    evidence_strength     TEXT,
    source_span           JSONB NOT NULL,             -- {section, char_start, char_end, verbatim_hash}
    extraction_confidence DOUBLE PRECISION,
    extracted_by          JSONB,                       -- {model, prompt_version, run_id}
    embedding            vector(1536),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_claims_paper_id ON claims(paper_id);

CREATE TABLE IF NOT EXISTS conflicts (
    conflict_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_a               UUID NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    claim_b               UUID NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    type                  TEXT,                       -- direct | conditional | methodological | numerical
    verdict               TEXT,                       -- genuine | scope_difference | extraction_error | insufficient_context
    adjudicator_rationale TEXT,
    confidence            DOUBLE PRECISION,
    adjudication_cost_usd DOUBLE PRECISION,
    loops_used            INTEGER NOT NULL DEFAULT 0,
    status                TEXT NOT NULL DEFAULT 'open', -- open | resolved | escalated_to_human
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_conflicts_status ON conflicts(status);

-- Hunter (embedding blocking) inserts (claim_a, claim_b) as an unadjudicated
-- candidate (verdict IS NULL); this stops re-running blocking from ever
-- creating a duplicate row for the same pair.
CREATE UNIQUE INDEX IF NOT EXISTS idx_conflicts_claim_pair ON conflicts(claim_a, claim_b);

-- Every pair the hunter's cheap classifier has looked at, regardless of
-- verdict -- lets a later blocking run skip pairs it's already screened.
-- Deliberately separate from `conflicts` (which mirrors plan.md §3.3's
-- Conflict schema exactly): "the hunter rejected this pair" isn't a Conflict
-- verdict, so it doesn't belong in that table.
CREATE TABLE IF NOT EXISTS hunter_screened_pairs (
    claim_a      UUID NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    claim_b      UUID NOT NULL REFERENCES claims(claim_id) ON DELETE CASCADE,
    is_candidate BOOLEAN NOT NULL,
    reason       TEXT,
    screened_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (claim_a, claim_b)
);

-- Labels produced by the review UI (web/) or the LLM-judge script
-- (evals/llm_judge.py). Feeds evals/golden/ (plan.md §5.1: "Label format =
-- same schemas as production"). One label per claim -- re-labeling overwrites
-- (ON CONFLICT), it isn't an audit log.
CREATE TABLE IF NOT EXISTS claim_labels (
    claim_id     UUID PRIMARY KEY REFERENCES claims(claim_id) ON DELETE CASCADE,
    verdict      TEXT NOT NULL,   -- correct | incorrect | uncertain
    notes        TEXT,
    labeled_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 'human' (via web/ UI) or 'llm_judge:<model>' (via evals/llm_judge.py). This
-- is load-bearing, not metadata: plan.md's golden set is explicitly defined
-- as independent human judgment (§5.1), so every consumer of claim_labels
-- (export_golden, report.py) must filter on this rather than treat every row
-- as equivalent ground truth.
ALTER TABLE claim_labels ADD COLUMN IF NOT EXISTS reviewer TEXT NOT NULL DEFAULT 'human';
