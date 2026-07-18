"""Living review -- the Week 5 public-facing output (plan.md §8's "Synthesis
Agent"). The contradiction table is the hero view: every adjudicated
conflict, both claims' quotes re-verified live against their papers (same
mechanism as web/app.py's claim review), full rationale, typed verdict.

Separate module from web/app.py (the internal golden-set labeling tool) on
purpose -- different audience, mounted into the same FastAPI app so both
share the DB connection pattern, retro theme, and templates directory.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from dissonance.extraction.fetch import fetch_full_text
from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, ConflictRepository, PaperRepository

BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")
router = APIRouter(prefix="/review")

# Separate from web/app.py's _TEXT_CACHE -- different process-lifetime cache,
# same rationale (avoid re-fetching a paper's HTML on every page view).
_TEXT_CACHE: dict[str, str | None] = {}


def _paper_text(paper_id: str) -> str | None:
    if paper_id not in _TEXT_CACHE:
        with get_connection() as conn:
            paper = PaperRepository(conn).get(paper_id)
        fetched = fetch_full_text(paper["html_url"], paper.get("abstract")) if paper else None
        _TEXT_CACHE[paper_id] = fetched.text if fetched else None
    return _TEXT_CACHE[paper_id]


def _quote_for(claim: dict) -> tuple[str | None, bool | None]:
    """Re-fetches the claim's paper and slices its verified span live --
    the quote is never stored in the DB (plan.md §3.2), so this is the same
    mechanical citation-faithfulness check web/app.py's paper_detail does."""
    text = _paper_text(claim["paper_id"])
    span = claim["source_span"]
    if text is None or span is None:
        return None, None
    quote = text[span["char_start"] : span["char_end"]]
    hash_ok = hashlib.sha256(quote.encode("utf-8")).hexdigest() == span.get("verbatim_hash")
    return quote, hash_ok


@router.get("", response_class=HTMLResponse)
def living_review(request: Request, verdict: str | None = None):
    with get_connection() as conn:
        conflict_repo = ConflictRepository(conn)
        conflicts = conflict_repo.list_adjudicated(limit=500, verdict=verdict)
        verdict_counts = conflict_repo.verdict_counts()
        paper_count = PaperRepository(conn).count()
        claim_count = ClaimRepository(conn).count()
    totals = {
        "papers": paper_count,
        "claims": claim_count,
        "adjudicated": sum(verdict_counts.values()),
        "genuine": verdict_counts.get("genuine", 0),
        "scope_difference": verdict_counts.get("scope_difference", 0),
        "insufficient_context": verdict_counts.get("insufficient_context", 0),
    }
    return templates.TemplateResponse(
        request,
        "living_review.html",
        {"conflicts": conflicts, "totals": totals, "active_filter": verdict},
    )


@router.get("/conflicts/{conflict_id}", response_class=HTMLResponse)
def conflict_detail(request: Request, conflict_id: str):
    with get_connection() as conn:
        conflict = ConflictRepository(conn).get_with_claims(conflict_id)
        if conflict is None:
            return HTMLResponse("404: no such conflict", status_code=404)
        claim_repo = ClaimRepository(conn)
        claim_a = claim_repo.get_full(str(conflict["claim_a"]))
        claim_b = claim_repo.get_full(str(conflict["claim_b"]))
        paper_a = PaperRepository(conn).get(claim_a["paper_id"]) if claim_a else None
        paper_b = PaperRepository(conn).get(claim_b["paper_id"]) if claim_b else None

    quote_a, hash_ok_a = _quote_for(claim_a) if claim_a else (None, None)
    quote_b, hash_ok_b = _quote_for(claim_b) if claim_b else (None, None)

    return templates.TemplateResponse(
        request,
        "conflict_detail.html",
        {
            "conflict": conflict,
            "claim_a": claim_a, "paper_a": paper_a, "quote_a": quote_a, "hash_ok_a": hash_ok_a,
            "claim_b": claim_b, "paper_b": paper_b, "quote_b": quote_b, "hash_ok_b": hash_ok_b,
        },
    )


@router.get("/escalated", response_class=HTMLResponse)
def escalation_queue(request: Request):
    with get_connection() as conn:
        conflicts = ConflictRepository(conn).list_escalated()
    return templates.TemplateResponse(request, "escalation_queue.html", {"conflicts": conflicts})


@router.post("/conflicts/{conflict_id}/override")
def override_conflict(conflict_id: str, verdict: str = Form(...), notes: str = Form("")):
    with get_connection() as conn:
        ConflictRepository(conn).human_override(conflict_id, verdict, notes)
    return RedirectResponse(url="/review/escalated", status_code=303)
