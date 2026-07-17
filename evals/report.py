"""Prints the honest-numbers table (plan.md §5.2). `python -m evals.report` or `make eval`.

Computes what's mechanically or statistically available right now:
  - citation faithfulness: for every claim in the graph, re-fetch its paper and
    check the stored span's hash. Purely mechanical -- no human labels needed.
  - extraction precision: correct / (correct + incorrect) from
    evals/golden/review_log.json, written by the review UI (web/app.py) each
    time "EXPORT GOLDEN SET" is clicked.
  - cost & loops: aggregated from runs/*/manifest.json.

What it does NOT compute, and says so rather than guessing:
  - recall: the review UI only triages claims the extractor already produced;
    it never asks a human to independently enumerate what SHOULD have been
    extracted from a paper. Without that second, independent pass, "recall"
    would be recall against nothing, so we print N/A instead of a number that
    looks precise but isn't.
  - contradiction detection / adjudication accuracy: hunter/adjudicator don't
    exist yet (plan.md Week 4).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Optional

from dissonance.extraction.fetch import fetch_full_text
from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, PaperRepository

GOLDEN_PATH = Path("evals/golden/claims.json")
REVIEW_LOG_PATH = Path("evals/golden/review_log.json")
RUNS_DIR = Path("runs")

V1_TARGETS = {
    "extraction_precision": 0.85,
    "extraction_recall": 0.70,
    "citation_faithfulness": 0.95,
}


def compute_precision(review_log: list[dict]) -> dict:
    correct = sum(1 for r in review_log if r["verdict"] == "correct")
    incorrect = sum(1 for r in review_log if r["verdict"] == "incorrect")
    uncertain = sum(1 for r in review_log if r["verdict"] == "uncertain")
    reviewed = correct + incorrect  # uncertain excluded from the denominator on purpose
    return {
        "correct": correct,
        "incorrect": incorrect,
        "uncertain": uncertain,
        "precision": (correct / reviewed) if reviewed else None,
    }


def compute_faithfulness(claims: list[dict], text_by_paper: dict[str, Optional[str]]) -> dict:
    checked = 0
    faithful = 0
    no_text = 0
    for c in claims:
        text = text_by_paper.get(c["paper_id"])
        if text is None:
            no_text += 1
            continue
        span = c["source_span"]
        quote = text[span["char_start"] : span["char_end"]]
        checked += 1
        if hashlib.sha256(quote.encode("utf-8")).hexdigest() == span.get("verbatim_hash"):
            faithful += 1
    return {
        "checked": checked,
        "faithful": faithful,
        "no_text": no_text,
        "total_claims": len(claims),
        "faithfulness_rate": (faithful / checked) if checked else None,
    }


def aggregate_extraction_runs(runs_dir: Path = RUNS_DIR) -> dict:
    total_cost = 0.0
    total_papers = 0
    loops_histogram: dict[str, int] = {}
    runs_seen = 0
    for manifest_path in runs_dir.glob("*/manifest.json"):
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if data.get("pipeline") != "extraction":
            continue
        runs_seen += 1
        total_cost += data.get("cost_usd", 0.0)
        total_papers += data.get("papers_touched", 0)
        for bucket, count in data.get("loops_to_resolution", {}).items():
            loops_histogram[bucket] = loops_histogram.get(bucket, 0) + count
    mean_loops = None
    if loops_histogram:
        total_units = sum(loops_histogram.values())
        weighted = sum(int(bucket) * count for bucket, count in loops_histogram.items())
        mean_loops = weighted / total_units
    return {
        "runs_seen": runs_seen,
        "total_cost_usd": total_cost,
        "total_papers": total_papers,
        "cost_per_paper": (total_cost / total_papers) if total_papers else None,
        "loops_histogram": loops_histogram,
        "mean_loops": mean_loops,
    }


def _fmt_pct(x: Optional[float]) -> str:
    return f"{x:.0%}" if x is not None else "N/A"


def print_report(precision: dict, faithfulness: dict, cost: dict, golden_count: int) -> None:
    # Windows consoles default stdout to cp1252, not utf-8 -- see manifest.py's
    # print_table() for the same fix and why it matters (non-ASCII survives
    # here even though it happened not to crash this time).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n=== dissonance eval report (plan.md §5.2) ===\n")
    print(f"{'eval':<26}{'metric':<14}{'v1 target':<12}{'current':<10}")
    print("-" * 62)
    print(f"{'claim extraction':<26}{'precision':<14}"
          f"{'>=' + _fmt_pct(V1_TARGETS['extraction_precision']):<12}{_fmt_pct(precision['precision']):<10}")
    print(f"{'':<26}{'recall':<14}"
          f"{'>=' + _fmt_pct(V1_TARGETS['extraction_recall']):<12}{'N/A *':<10}")
    print(f"{'citation faithfulness':<26}{'% faithful':<14}"
          f"{'>=' + _fmt_pct(V1_TARGETS['citation_faithfulness']):<12}{_fmt_pct(faithfulness['faithfulness_rate']):<10}")
    print(f"{'contradiction detection':<26}{'P/R':<14}{'>=80%/60%':<12}{'N/A **':<10}")
    print(f"{'adjudication verdict':<26}{'agreement':<14}{'>=80%':<12}{'N/A **':<10}")

    print("\n--- claim extraction ---")
    reviewed = precision["correct"] + precision["incorrect"]
    print(f"reviewed: {reviewed} (correct={precision['correct']}, incorrect={precision['incorrect']}, "
          f"uncertain={precision['uncertain']} excluded from precision denominator)")
    print(f"golden claims exported: {golden_count}")

    print("\n--- citation faithfulness ---")
    print(f"claims in graph: {faithfulness['total_claims']}, "
          f"checked (source text available): {faithfulness['checked']}, "
          f"faithful: {faithfulness['faithful']}, no source text: {faithfulness['no_text']}")

    print("\n--- cost & loops (extraction runs) ---")
    if cost["runs_seen"] == 0:
        print("no extraction run manifests found in runs/")
    else:
        cost_per_paper = f"${cost['cost_per_paper']:.4f}" if cost["cost_per_paper"] is not None else "N/A"
        print(f"runs: {cost['runs_seen']}, papers: {cost['total_papers']}, "
              f"total cost: ${cost['total_cost_usd']:.4f}, cost/paper: {cost_per_paper}")
        mean_loops = f"{cost['mean_loops']:.2f}" if cost["mean_loops"] is not None else "N/A"
        print(f"loops-to-resolution histogram: {cost['loops_histogram']}, mean: {mean_loops}")

    print("\n* recall requires a human to independently enumerate the claims a careful")
    print("  reading of each paper SHOULD produce, then compare against what the")
    print("  extractor found. The review UI only triages claims the extractor already")
    print("  produced (a precision signal) -- not built yet.")
    print("** hunter/adjudicator don't exist yet (plan.md Week 4).")
    print()


def main() -> None:
    review_log = json.loads(REVIEW_LOG_PATH.read_text(encoding="utf-8")) if REVIEW_LOG_PATH.exists() else []
    golden_claims = json.loads(GOLDEN_PATH.read_text(encoding="utf-8")) if GOLDEN_PATH.exists() else []
    precision = compute_precision(review_log)

    with get_connection() as conn:
        all_claims = ClaimRepository(conn).list_all()
        paper_repo = PaperRepository(conn)
        paper_ids = sorted({c["paper_id"] for c in all_claims})
        text_by_paper: dict[str, Optional[str]] = {}
        for pid in paper_ids:
            paper = paper_repo.get(pid)
            if paper is None:
                text_by_paper[pid] = None
                continue
            fetched = fetch_full_text(paper["html_url"], paper.get("abstract"))
            text_by_paper[pid] = fetched.text

    faithfulness = compute_faithfulness(all_claims, text_by_paper)
    cost = aggregate_extraction_runs()

    print_report(precision, faithfulness, cost, len(golden_claims))


if __name__ == "__main__":
    main()
