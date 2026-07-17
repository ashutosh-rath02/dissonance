"""Extract typed claims from papers already ingested by scouts. One command, one manifest.

    python -m dissonance.extraction.run --limit 10 --workers 8

Exit test for plan.md Week 2: N papers -> claims in graph.

Runs papers concurrently across a thread pool (plan.md §3.1 calls extraction
"embarrassingly parallel" -- each paper's fetch+extract+store is independent
I/O-bound work, so threading is enough without an async rewrite). The
Extractor and OpenAI client are shared across workers (both are documented
thread-safe); each worker still opens its own DB connection per paper, same
as the original sequential design -- psycopg connections aren't meant to be
shared across threads.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from dissonance.extraction.extractor import Extractor
from dissonance.extraction.pipeline import extract_paper
from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, PaperRepository
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor
from dissonance.supervisor.exceptions import IdenticalFailureBreakerTripped


def process_paper(paper: dict, run_config: RunConfig, supervisor: Supervisor, extractor: Extractor) -> None:
    if supervisor.budget.halted:
        return

    with supervisor.stage("extraction"):
        # One connection per paper (not per run): a crash mid-run, or another
        # worker's error, should not lose this paper's already-committed claims.
        with get_connection() as conn:
            paper_repo = PaperRepository(conn)
            claim_repo = ClaimRepository(conn)

            try:
                outcome = extract_paper(paper, run_config, extractor, supervisor.run_id)
            except IdenticalFailureBreakerTripped as exc:
                supervisor.note(f"{paper['paper_id']}: identical-failure breaker tripped ({exc})")
                paper_repo.update_extraction_status(paper["paper_id"], "quarantined")
                return
            except Exception as exc:  # noqa: BLE001 - one bad paper must not sink the batch
                supervisor.note(f"{paper['paper_id']}: unexpected error, left pending for retry: {exc}")
                return

            supervisor.spend("extraction", outcome.cost_usd)
            for note in outcome.notes:
                supervisor.note(f"{paper['paper_id']}: {note}")

            if outcome.claim_records:
                claim_repo.insert_claims(outcome.claim_records)
                supervisor.increment("claims_added", len(outcome.claim_records))

            paper_repo.update_full_text_status(paper["paper_id"], outcome.full_text_status)
            paper_repo.update_extraction_status(paper["paper_id"], outcome.extraction_status)
            if outcome.extraction_status != "pending":
                supervisor.increment("papers_touched", 1)
                supervisor.record_loops_to_resolution(outcome.attempts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract typed claims from ingested papers")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--workers", type=int, default=8, help="concurrent extraction workers")
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    supervisor = Supervisor(run_config, pipeline="extraction")
    extractor = Extractor()

    with get_connection() as conn:
        papers = PaperRepository(conn).papers_needing_extraction(args.limit)
    supervisor.note(f"{len(papers)} papers pending extraction ({args.workers} workers)")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(process_paper, paper, run_config, supervisor, extractor) for paper in papers]
        for future in as_completed(futures):
            future.result()  # re-raise anything that escaped process_paper's own handling

    manifest = supervisor.finalize()
    manifest.print_table()


if __name__ == "__main__":
    main()
