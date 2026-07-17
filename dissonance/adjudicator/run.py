"""Tiered adjudicator: reads full-text context for both claims in a suspected
conflict and reaches a typed verdict. `python -m dissonance.adjudicator.run --limit N --workers 10`

Exit test for plan.md Week 4 (paired with the hunter): finds >= 10 genuine
conflicts in the corpus with rationales worth reading.

Runs conflicts concurrently across a thread pool -- same rationale as
extraction/hunter. Known race, accepted rather than engineered around: if the
same claim appears in two conflict pairs processed by different workers at
once, and one resolves with verdict=extraction_error (deleting that claim),
the other worker's concurrent UPDATE to its own conflict row may silently
no-op if the cascade already removed it. Rare in practice (few claims appear
in more than one candidate pair) and harmless when it happens (lost work, not
corruption) -- not worth a locking scheme for.
"""

from __future__ import annotations

import argparse
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
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


class TextCache:
    """Thread-safe memoized paper-text fetch, shared across adjudicator workers."""

    def __init__(self) -> None:
        self._cache: dict[str, Optional[str]] = {}
        self._lock = threading.Lock()

    def get(self, paper_id: str) -> Optional[str]:
        with self._lock:
            if paper_id in self._cache:
                return self._cache[paper_id]
        with get_connection() as conn:
            paper = PaperRepository(conn).get(paper_id)
        fetched = fetch_full_text(paper["html_url"], paper.get("abstract")) if paper else None
        text = fetched.text if fetched else None
        with self._lock:
            self._cache[paper_id] = text
        return text


def adjudicate_one(
    conflict: dict, run_config: RunConfig, supervisor: Supervisor, client: AdjudicatorClient, text_cache: TextCache
) -> Optional[str]:
    """Returns the verdict reached, or None if this conflict wasn't processed
    (already halted, claim missing, or a transient error)."""
    if supervisor.budget.halted:
        return None

    with supervisor.stage("adjudicator"):
        with get_connection() as conn:
            claim_repo = ClaimRepository(conn)
            claim_a = claim_repo.get_full(str(conflict["claim_a"]))
            claim_b = claim_repo.get_full(str(conflict["claim_b"]))
        if claim_a is None or claim_b is None:
            # Already deleted by a concurrent extraction_error resolution
            # (cascade) -- see module docstring.
            return None

        try:
            text_a = text_cache.get(claim_a["paper_id"])
            text_b = text_cache.get(claim_b["paper_id"])
        except Exception as exc:  # noqa: BLE001 - same class of transient fetch failure fixed elsewhere
            supervisor.note(f"{conflict['conflict_id']}: fetch failed, skipping this run: {exc}")
            return None

        context_a = context_window(text_a, claim_a["source_span"]) if text_a else claim_a["assertion"]
        context_b = context_window(text_b, claim_b["source_span"]) if text_b else claim_b["assertion"]

        try:
            outcome = adjudicate_pair(claim_a, context_a, claim_b, context_b, run_config, client)
        except Exception as exc:  # noqa: BLE001 - one bad pair shouldn't sink the batch
            supervisor.note(f"{conflict['conflict_id']}: adjudication call failed, skipped: {exc}")
            return None

        supervisor.spend("adjudicator", outcome.cost_usd)
        supervisor.record_loops_to_resolution(outcome.loops_used)

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
            return outcome.verdict

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
        return outcome.verdict


def main() -> None:
    parser = argparse.ArgumentParser(description="Adjudicate suspected contradiction pairs")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--workers", type=int, default=8, help="concurrent adjudication workers")
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    supervisor = Supervisor(run_config, pipeline="adjudicator")
    client = AdjudicatorClient()
    text_cache = TextCache()

    with get_connection() as conn:
        pending = ConflictRepository(conn).needing_adjudication(args.limit)
    supervisor.note(f"{len(pending)} conflicts pending adjudication ({args.workers} workers)")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(adjudicate_one, conflict, run_config, supervisor, client, text_cache)
            for conflict in pending
        ]
        verdicts = [f.result() for f in as_completed(futures)]

    verdict_counts: dict[str, int] = {}
    for v in verdicts:
        if v is not None:
            verdict_counts[v] = verdict_counts.get(v, 0) + 1

    manifest = supervisor.finalize()
    manifest.print_table()
    print(f"verdicts this run: {verdict_counts}")


if __name__ == "__main__":
    main()
