"""Ingest a corpus for the pilot domain. One command, one manifest.

    python -m dissonance.scouts.run --limit 250

Exit test for plan.md Week 1: prints a manifest with paper counts and cost
(arXiv is free, so cost is always $0 for this stage).

Default query is field-scoped and relevance-sorted (see DEFAULT_QUERY below) --
the original naive `all:"LLM evaluation"` sorted by submission date mostly
returns whatever was posted most recently that loosely matches, which turned
out to pull a topically broad, poorly-scoped sample (physics, GPU hardware,
medical robotics alongside actual LLM-eval papers -- see plan.md Week 4's
corpus-scoping finding in docs/architecture.md). Pass --query to override.
"""

from __future__ import annotations

import argparse

from dissonance.graph.db import get_connection
from dissonance.graph.repository import PaperRepository
from dissonance.scouts.arxiv import ArxivScout
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor

DEFAULT_QUERY = (
    'cat:cs.CL AND abs:"language model" AND '
    '(abs:evaluation OR abs:benchmark OR abs:benchmarking OR '
    'abs:"LLM-as-a-judge" OR abs:contamination OR abs:"judge reliability")'
)

# Foundational/famous benchmark and technique papers -- title-scoped (not
# abstract) so this matches the paper that INTRODUCED the benchmark, not
# every later paper that merely evaluates on it. These are exactly the papers
# later work builds on, argues with, or reports contamination/validity
# concerns about -- high contradiction density by construction, and mostly
# older than a relevance/date search over recent submissions would surface.
FAMOUS_QUERY = (
    'cat:cs.CL AND '
    '(ti:"MMLU" OR ti:"HellaSwag" OR ti:"TruthfulQA" OR ti:"BIG-bench" OR '
    'ti:"HELM" OR ti:"Chatbot Arena" OR ti:"MT-Bench" OR ti:"AlpacaEval" OR '
    'ti:"GPQA" OR ti:"GSM8K" OR ti:"HumanEval" OR ti:"ARC" OR '
    'ti:"data contamination" OR ti:"benchmark contamination" OR '
    'ti:"LLM-as-a-judge" OR ti:"G-Eval")'
)

PRESETS = {"default": DEFAULT_QUERY, "famous": FAMOUS_QUERY}


def main() -> None:
    parser = argparse.ArgumentParser(description="Scout arXiv for the pilot domain corpus")
    parser.add_argument("--query", default=None, help="raw arXiv query; overrides --preset if given")
    parser.add_argument("--preset", default="default", choices=list(PRESETS), help="named query, see PRESETS")
    parser.add_argument(
        "--simple-query",
        action="store_true",
        help="treat --query as a loose keyword phrase (all:...) instead of raw arXiv query syntax",
    )
    parser.add_argument("--sort-by", default="relevance", choices=["relevance", "submittedDate", "lastUpdatedDate"])
    parser.add_argument("--start", type=int, default=0, help="pagination offset, for pulling beyond the first page")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()
    query = args.query or PRESETS[args.preset]

    run_config = RunConfig.load(args.config)
    supervisor = Supervisor(run_config, pipeline="ingest")

    scout = ArxivScout()
    try:
        with supervisor.stage("scouts"):
            papers = scout.search(
                query,
                max_results=args.limit,
                start=args.start,
                raw_query=not args.simple_query,
                sort_by=args.sort_by,
            )
            supervisor.spend("scouts", 0.0)
            supervisor.note(f"arxiv query={query!r} (sort_by={args.sort_by}, start={args.start}) returned {len(papers)} papers")
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
