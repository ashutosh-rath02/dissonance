"""Claim review UI -- the Week 3 golden-set labeling tool (plan.md §5.1).

    uvicorn web.app:app --reload

Browse ingested papers, review each extracted claim next to its verified
source quote, and label it correct/incorrect/uncertain. Claims labeled
"correct" export to evals/golden/claims.json, in the same schema production
uses (plan.md §3.2) -- that's the golden set the eval harness (Week 3) scores
extraction against.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dissonance.extraction.fetch import fetch_full_text
from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, LabelRepository, PaperRepository
from web.living_review import router as living_review_router

BASE_DIR = Path(__file__).parent
GOLDEN_PATH = Path("evals/golden/claims.json")
REVIEW_LOG_PATH = Path("evals/golden/review_log.json")
# claims.source_span stores only char offsets + a hash, not the quote text
# itself (plan.md §3.2 by design -- don't duplicate paper text in the DB).
# Citation-faithfulness checking is meant to be mechanical: re-fetch the
# paper, slice the span, compare the hash. This cache just avoids re-fetching
# on every page view while reviewing the same paper's claims.
_TEXT_CACHE: dict[str, str | None] = {}

app = FastAPI(title="Dissonance")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(living_review_router)
templates = Jinja2Templates(directory=BASE_DIR / "templates")


def _paper_text(paper: dict) -> str | None:
    if paper["paper_id"] not in _TEXT_CACHE:
        fetched = fetch_full_text(paper["html_url"], paper.get("abstract"))
        _TEXT_CACHE[paper["paper_id"]] = fetched.text
    return _TEXT_CACHE[paper["paper_id"]]


def _attach_quotes(claims: list[dict], text: str | None) -> None:
    for c in claims:
        span = c["source_span"]
        if not text or span is None:
            c["quote"] = None
            c["hash_ok"] = None
            continue
        quote = text[span["char_start"] : span["char_end"]]
        c["quote"] = quote
        c["hash_ok"] = hashlib.sha256(quote.encode("utf-8")).hexdigest() == span.get("verbatim_hash")


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, exported: int | None = None):
    with get_connection() as conn:
        papers = PaperRepository(conn).list_with_stats()
        labels = LabelRepository(conn)
        human_verdicts = labels.verdict_counts(reviewer="human")
        reviewer_counts = labels.reviewer_counts()
    llm_judge_labeled = sum(n for r, n in reviewer_counts.items() if r != "human")
    totals = {
        "papers": len(papers),
        "claims": sum(p["claim_count"] for p in papers),
        "human_labeled": sum(p["human_labeled_count"] for p in papers),
        # Dashboard only ever shows HUMAN verdicts -- this is the golden-set
        # signal plan.md §5.1 means. LLM-judge counts are shown separately,
        # never merged in, so the stat bar can't be misread as ground truth.
        "correct": human_verdicts.get("correct", 0),
        "incorrect": human_verdicts.get("incorrect", 0),
        "uncertain": human_verdicts.get("uncertain", 0),
        "llm_judge_labeled": llm_judge_labeled,
    }
    return templates.TemplateResponse(
        request, "dashboard.html", {"papers": papers, "totals": totals, "exported": exported}
    )


@app.get("/papers/{paper_id}", response_class=HTMLResponse)
def paper_detail(request: Request, paper_id: str):
    with get_connection() as conn:
        paper = PaperRepository(conn).get(paper_id)
        claims = ClaimRepository(conn).list_for_paper(paper_id) if paper else []
    if paper is None:
        return HTMLResponse("404: no such paper", status_code=404)
    text = _paper_text(paper)
    _attach_quotes(claims, text)
    return templates.TemplateResponse(
        request,
        "paper.html",
        {"paper": paper, "claims": claims, "text_available": text is not None},
    )


@app.post("/claims/{claim_id}/label")
def label_claim(
    claim_id: str,
    paper_id: str = Form(...),
    verdict: str = Form(...),
    notes: str = Form(""),
):
    with get_connection() as conn:
        LabelRepository(conn).upsert(claim_id, verdict, notes or None, reviewer="human")
    return RedirectResponse(url=f"/papers/{paper_id}#claim-{claim_id}", status_code=303)


@app.post("/export/golden")
def export_golden():
    with get_connection() as conn:
        labels = LabelRepository(conn)
        golden_rows = labels.export_golden()
        review_log = labels.export_review_log()

    shaped = [_to_claim_schema(r) for r in golden_rows]
    GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    GOLDEN_PATH.write_text(json.dumps(shaped, indent=2, default=str), encoding="utf-8")

    # review_log.json carries every verdict (not just "correct"), which
    # claims.json alone can't -- evals/report.py needs the full denominator
    # to compute precision, not just the positive examples.
    log_shaped = [
        {
            "claim_id": str(r["claim_id"]),
            "paper_id": r["paper_id"],
            "verdict": r["verdict"],
            "notes": r["notes"],
            "reviewer": r["reviewer"],
            "labeled_at": r["labeled_at"].isoformat(),
        }
        for r in review_log
    ]
    REVIEW_LOG_PATH.write_text(json.dumps(log_shaped, indent=2), encoding="utf-8")

    return RedirectResponse(url=f"/?exported={len(shaped)}", status_code=303)


def _to_claim_schema(row: dict) -> dict:
    """Shape a DB row into exactly plan.md §3.2's Claim JSON schema."""
    return {
        "claim_id": str(row["claim_id"]),
        "paper_id": row["paper_id"],
        "assertion": row["assertion"],
        "subject": row["subject"],
        "object": row["object"],
        "direction": row["direction"],
        "effect_size": row["effect_size"],
        "conditions": row["conditions"],
        "method_type": row["method_type"],
        "evidence_strength": row["evidence_strength"],
        "source_span": row["source_span"],
        "extraction_confidence": row["extraction_confidence"],
        "extracted_by": row["extracted_by"],
    }
