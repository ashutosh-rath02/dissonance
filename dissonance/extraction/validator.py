from __future__ import annotations

import hashlib
import uuid

from dissonance.extraction.schema import ExtractedClaim


class SpanNotFoundError(ValueError):
    """The model's `quote` doesn't appear verbatim in the source text.

    This is the mechanical citation-faithfulness check plan.md §3.2 describes:
    re-open the paper, check the span supports the assertion. If we can't even
    find the span, we can't trust the claim.
    """

    def __init__(self, quote: str):
        self.quote = quote
        super().__init__(f"quote not found verbatim in source text: {quote[:80]!r}")


def build_claim_record(
    *,
    paper_id: str,
    claim: ExtractedClaim,
    source_text: str,
    model: str,
    prompt_version: str,
    run_id: str,
) -> dict:
    """Validate a model-extracted claim against its source and shape it into a
    row matching dissonance/graph/schema.sql's claims table."""
    start = source_text.find(claim.quote)
    if start == -1:
        raise SpanNotFoundError(claim.quote)
    end = start + len(claim.quote)
    verbatim_hash = hashlib.sha256(claim.quote.encode("utf-8")).hexdigest()

    return {
        "claim_id": str(uuid.uuid4()),
        "paper_id": paper_id,
        "assertion": claim.assertion,
        "subject": claim.subject,
        "object": claim.object,
        "direction": claim.direction,
        "effect_size": claim.effect_size.model_dump(),
        "conditions": claim.conditions.model_dump(),
        "method_type": claim.method_type,
        "evidence_strength": claim.evidence_strength,
        "source_span": {
            "section": claim.section,
            "char_start": start,
            "char_end": end,
            "verbatim_hash": verbatim_hash,
        },
        "extraction_confidence": claim.confidence,
        "extracted_by": {"model": model, "prompt_version": prompt_version, "run_id": run_id},
    }
