"""Tiered adjudicator: reads full-text context for both claims in a suspected
conflict and reaches a typed verdict. `python -m dissonance.adjudicator.run --limit N`

Exit test for plan.md Week 4 (paired with the hunter): finds >= 10 genuine
conflicts in the corpus with rationales worth reading.
"""

from __future__ import annotations

import argparse
from typing import Optional

from dissonance.adjudicator.client import AdjudicatorClient
from dissonance.adjudicator.context import context_window
from dissonance.adjudicator.pipeline import adjudicate_pair
from dissonance.extraction.fetch import fetch_full_text
from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, ConflictRepository, PaperRepository
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor

# Status a resolved conflict lands in, keyed by verdict -- "genuine" stays
# "open" because that's the interesting output the Week 5 living review
# surfaces; "insufficient_context" goes to Week 5's human escalation queue.
STATUS_BY_VERDICT = {
    "genuine": "open",
    "scope_difference": "resolved",
    "insufficient_context": "escalated_to_human",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Adjudicate suspected contradiction pairs")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    supervisor = Supervisor(run_config, pipeline="adjudicator")
    client = AdjudicatorClient()

    with get_connection() as conn:
        pending = ConflictRepository(conn).needing_adjudication(args.limit)
    supervisor.note(f"{len(pending)} conflicts pending adjudication")

    text_cache: dict[str, Optional[str]] = {}
    verdict_counts: dict[str, int] = {}

    def get_text(paper_id: str) -> Optional[str]:
        if paper_id not in text_cache:
            with get_connection() as conn:
                paper = PaperRepository(conn).get(paper_id)
            fetched = fetch_full_text(paper["html_url"], paper.get("abstract")) if paper else None
            text_cache[paper_id] = fetched.text if fetched else None
        return text_cache[paper_id]

    for conflict in pending:
        if supervisor.budget.halted:
            supervisor.note(f"budget halted, stopping before conflict {conflict['conflict_id']}")
            break

        with supervisor.stage("adjudicator"):
            with get_connection() as conn:
                claim_repo = ClaimRepository(conn)
                claim_a = claim_repo.get_full(str(conflict["claim_a"]))
                claim_b = claim_repo.get_full(str(conflict["claim_b"]))
            if claim_a is None or claim_b is None:
                # One side already got deleted by an earlier extraction_error
                # resolution this run; cascade already removed this conflict row.
                continue

            try:
                text_a = get_text(claim_a["paper_id"])
                text_b = get_text(claim_b["paper_id"])
            except Exception as exc:  # noqa: BLE001 - same class of transient fetch failure fixed elsewhere
                supervisor.note(f"{conflict['conflict_id']}: fetch failed, skipping this run: {exc}")
                continue

            context_a = context_window(text_a, claim_a["source_span"]) if text_a else claim_a["assertion"]
            context_b = context_window(text_b, claim_b["source_span"]) if text_b else claim_b["assertion"]

            try:
                outcome = adjudicate_pair(claim_a, context_a, claim_b, context_b, run_config, client)
            except Exception as exc:  # noqa: BLE001 - one bad pair shouldn't sink the batch
                supervisor.note(f"{conflict['conflict_id']}: adjudication call failed, skipped: {exc}")
                continue

            supervisor.spend("adjudicator", outcome.cost_usd)
            supervisor.record_loops_to_resolution(outcome.loops_used)
            verdict_counts[outcome.verdict] = verdict_counts.get(outcome.verdict, 0) + 1

            if outcome.verdict == "extraction_error":
                bad_claim = claim_a if outcome.extraction_error_claim == "A" else claim_b
                supervisor.note(
                    f"{conflict['conflict_id']}: extraction_error on claim {bad_claim['claim_id']} "
                    f"(paper {bad_claim['paper_id']}) -- {outcome.rationale}"
                )
                with get_connection() as conn:
                    # Deleting the claim cascades away this conflict row (FK
                    # ON DELETE CASCADE) -- the run manifest note above is the
                    # permanent record of why, since the row itself won't survive.
                    ClaimRepository(conn).delete(str(bad_claim["claim_id"]))
                    PaperRepository(conn).update_extraction_status(bad_claim["paper_id"], "pending")
                supervisor.increment("conflicts_adjudicated", 0)  # not a resolved conflict, just cleanup
                continue

            status = STATUS_BY_VERDICT[outcome.verdict]
            with get_connection() as conn:
                ConflictRepository(conn).update_verdict(
                    str(conflict["conflict_id"]),
                    type_=outcome.type,
                    verdict=outcome.verdict,
                    rationale=outcome.rationale,
                    confidence=outcome.confidence,
                    cost_usd=outcome.cost_usd,
                    loops_used=outcome.loops_used,
                    status=status,
                )
            supervisor.increment("conflicts_adjudicated", 1)
            supervisor.note(
                f"{conflict['conflict_id']}: {outcome.type}/{outcome.verdict} "
                f"(confidence={outcome.confidence:.2f}, loops={outcome.loops_used}) -- {outcome.rationale}"
            )

    manifest = supervisor.finalize()
    manifest.print_table()
    print(f"verdicts this run: {verdict_counts}")


if __name__ == "__main__":
    main()
