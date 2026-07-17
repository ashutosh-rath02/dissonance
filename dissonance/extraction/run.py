"""Extract typed claims from papers already ingested by scouts. One command, one manifest.

    python -m dissonance.extraction.run --limit 10

Exit test for plan.md Week 2: N papers -> claims in graph.
"""

from __future__ import annotations

import argparse

from dissonance.extraction.extractor import Extractor
from dissonance.extraction.pipeline import extract_paper
from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, PaperRepository
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor
from dissonance.supervisor.exceptions import IdenticalFailureBreakerTripped


def main() -> None:
    parser = argparse.ArgumentParser(description="Extract typed claims from ingested papers")
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    supervisor = Supervisor(run_config, pipeline="extraction")
    extractor = Extractor()

    with get_connection() as conn:
        papers = PaperRepository(conn).papers_needing_extraction(args.limit)
    supervisor.note(f"{len(papers)} papers pending extraction")

    for paper in papers:
        if supervisor.budget.halted:
            supervisor.note(f"budget halted, stopping before paper {paper['paper_id']}")
            break

        with supervisor.stage("extraction"):
            # One connection per paper: a crash mid-run should not lose
            # already-committed papers' claims.
            with get_connection() as conn:
                paper_repo = PaperRepository(conn)
                claim_repo = ClaimRepository(conn)

                try:
                    outcome = extract_paper(paper, run_config, extractor, supervisor.run_id)
                except IdenticalFailureBreakerTripped as exc:
                    supervisor.note(f"{paper['paper_id']}: identical-failure breaker tripped ({exc})")
                    paper_repo.update_extraction_status(paper["paper_id"], "quarantined")
                    continue
                except Exception as exc:  # noqa: BLE001 - one bad paper must not sink the batch
                    supervisor.note(f"{paper['paper_id']}: unexpected error, left pending for retry: {exc}")
                    continue

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

    manifest = supervisor.finalize()
    manifest.print_table()


if __name__ == "__main__":
    main()
