from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class AdjudicatorVerdict(BaseModel):
    # `rationale` is declared FIRST on purpose. OpenAI structured outputs
    # generate JSON fields in schema declaration order -- if `verdict` came
    # first, the model commits to a conclusion before writing the reasoning
    # that's supposed to justify it, and the two can end up contradicting
    # each other (observed for real: multiple "genuine" verdicts whose own
    # rationale said "there is no contradiction"). Reasoning-before-answer is
    # the fix, not a prompt tweak -- field order IS the causal mechanism here.
    rationale: str
    type: Literal["direct", "conditional", "methodological", "numerical"]
    verdict: Literal["genuine", "scope_difference", "extraction_error", "insufficient_context"]
    # Required (by the prompt, not the schema -- structured outputs can't do
    # conditional-required) when verdict == "extraction_error": which claim's
    # extraction is the problem, so the re-extraction loop knows what to delete.
    extraction_error_claim: Optional[Literal["A", "B"]] = None
    confidence: float
