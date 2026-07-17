from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class EffectSize(BaseModel):
    value: Optional[float] = None
    unit: Optional[str] = None
    reported: bool


class Conditions(BaseModel):
    model_class: Optional[str] = None
    population_or_setting: Optional[str] = None
    other: list[str] = Field(default_factory=list)


class ExtractedClaim(BaseModel):
    """What the model returns. `quote` must be copied verbatim from the input
    text -- it's how we compute source_span/verbatim_hash without trusting the
    model to count characters (plan.md §3.2).

    Field order is evidence-first on purpose: `quote`/`section` before the
    interpretive fields derived from them. Structured outputs fill fields in
    declaration order, so the model should locate and copy its evidence
    before it starts characterizing what that evidence says -- see
    dissonance/adjudicator/schema.py's AdjudicatorVerdict for a case where
    getting this order backwards (conclusion before reasoning) produced
    verdicts that contradicted their own rationale."""

    quote: str
    section: str
    assertion: str
    subject: str
    object: str
    direction: Literal["increases", "decreases", "no_effect", "mixed"]
    effect_size: EffectSize
    conditions: Conditions
    method_type: Literal[
        "benchmark_eval", "ablation", "rct", "observational", "theoretical", "survey"
    ]
    evidence_strength: Literal["primary_result", "secondary_result", "cited_claim"]
    confidence: float


class ExtractionResult(BaseModel):
    claims: list[ExtractedClaim]
