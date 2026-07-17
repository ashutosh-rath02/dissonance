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
