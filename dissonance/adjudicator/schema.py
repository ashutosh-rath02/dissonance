from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel


class AdjudicatorVerdict(BaseModel):
    type: Literal["direct", "conditional", "methodological", "numerical"]
    verdict: Literal["genuine", "scope_difference", "extraction_error", "insufficient_context"]
    # Required (by the prompt, not the schema -- structured outputs can't do
    # conditional-required) when verdict == "extraction_error": which claim's
    # extraction is the problem, so the re-extraction loop knows what to delete.
    extraction_error_claim: Optional[Literal["A", "B"]] = None
    rationale: str
    confidence: float
