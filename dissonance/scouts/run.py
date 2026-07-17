"""Ingest a corpus for the pilot domain. One command, one manifest.

    python -m dissonance.scouts.run --query "LLM evaluation" --limit 50

Exit test for plan.md Week 1: prints a manifest with paper counts and cost
(arXiv is free, so cost is always $0 for this stage).
"""

from __future__ import annotations

import argparse

from dissonance.graph.db import get_connection
from dissonance.graph.repository import PaperRepository
from dissonance.scouts.arxiv import ArxivScout
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor


def main() -> None:
    parser = argparse.ArgumentParser(description="Scout arXiv for the pilot domain corpus")
    parser.add_argument("--query", default="LLM evaluation")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    supervisor = Supervisor(run_config, pipeline="ingest")

    scout = ArxivScout()
    try:
        with supervisor.stage("scouts"):
            papers = scout.search(args.query, max_results=args.limit)
            supervisor.spend("scouts", 0.0)
            supervisor.note(f"arxiv query={args.query!r} returned {len(papers)} papers")
    finally:
        scout.close()

    with supervisor.stage("graph"):
        with get_connection() as conn:
            repo = PaperRepository(conn)
            result = repo.upsert_many(papers)
        supervisor.increment("papers_touched", result.touched)
        supervisor.increment("papers_new", result.new)

    manifest = supervisor.finalize()
    manifest.print_table()


if __name__ == "__main__":
    main()
