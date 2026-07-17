from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class Paper(BaseModel):
    paper_id: str                      # 'arxiv:2501.01234'
    arxiv_id: Optional[str] = None
    doi: Optional[str] = None
    title: str
    abstract: Optional[str] = None
    authors: list[str] = []
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    primary_category: Optional[str] = None
    categories: list[str] = []
    pdf_url: Optional[str] = None
    html_url: Optional[str] = None
    source: Literal["arxiv", "openalex", "semanticscholar"]
    full_text_status: Literal["html_available", "pdf_only", "abstract_only", "unknown"] = "unknown"


class Claim(BaseModel):
    """Mirrors plan.md §3.2. Not populated until Week 2 (extraction swarm)."""

    claim_id: str
    paper_id: str
    assertion: str
    subject: Optional[str] = None
    object: Optional[str] = None
    direction: Optional[Literal["increases", "decreases", "no_effect", "mixed"]] = None
    effect_size: Optional[dict] = None
    conditions: Optional[dict] = None
    method_type: Optional[str] = None
    evidence_strength: Optional[str] = None
    source_span: dict
    extraction_confidence: float = 0.0
    extracted_by: Optional[dict] = None


class Conflict(BaseModel):
    """Mirrors plan.md §3.3. Not populated until Week 4 (adjudicator)."""

    conflict_id: str
    claim_a: str
    claim_b: str
    type: Optional[Literal["direct", "conditional", "methodological", "numerical"]] = None
    verdict: Optional[Literal["genuine", "scope_difference", "extraction_error", "insufficient_context"]] = None
    adjudicator_rationale: Optional[str] = None
    confidence: float = 0.0
    adjudication_cost_usd: float = 0.0
    loops_used: int = 0
    status: Literal["open", "resolved", "escalated_to_human"] = "open"
