"""Contradiction hunter: embedding blocking + cheap classifier -> suspected conflicts.

    python -m dissonance.hunter.run --limit-pairs 200 --workers 10

Backfills any missing claim embeddings, finds cross-paper candidate pairs by
cosine similarity (plan.md §3.1's "embedding blocking"), then runs a cheap
classifier over each candidate to filter out pairs that are only
superficially similar. Flagged pairs land in `conflicts` with verdict=NULL,
ready for `python -m dissonance.adjudicator.run`. Both the embedding backfill
and the pair-screening loop run across a thread pool -- same rationale as
dissonance/extraction/run.py: I/O-bound API calls, embarrassingly parallel
per plan.md §3.1.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, ConflictRepository
from dissonance.hunter.classifier import HunterClassifier
from dissonance.hunter.embeddings import EmbeddingClient, embedding_text
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor


def embed_one(claim: dict, run_config: RunConfig, supervisor: Supervisor, embedder: EmbeddingClient) -> None:
    if supervisor.budget.halted:
        return
    with supervisor.stage("hunter"):
        try:
            result = embedder.embed(embedding_text(claim), run_config.embedding)
        except Exception as exc:  # noqa: BLE001 - one bad claim shouldn't sink the batch
            supervisor.note(f"{claim['claim_id']}: embedding failed, skipped: {exc}")
            return
        supervisor.spend("hunter", result.cost_usd)
        with get_connection() as conn:
            ClaimRepository(conn).update_embedding(str(claim["claim_id"]), result.vector)


def backfill_embeddings(
    supervisor: Supervisor, run_config: RunConfig, embedder: EmbeddingClient, workers: int
) -> int:
    total = 0
    while True:
        with get_connection() as conn:
            claims = ClaimRepository(conn).claims_missing_embeddings(200)
        if not claims or supervisor.budget.halted:
            break
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = [pool.submit(embed_one, c, run_config, supervisor, embedder) for c in claims]
            for future in as_completed(futures):
                future.result()
        total += len(claims)
    return total


def screen_one(
    pair: dict, tier, supervisor: Supervisor, classifier: HunterClassifier
) -> bool:
    """Returns True if this pair was flagged as a suspected conflict."""
    if supervisor.budget.halted:
        return False
    with supervisor.stage("hunter"):
        with get_connection() as conn:
            claim_repo = ClaimRepository(conn)
            claim_a = claim_repo.get_full(pair["claim_a"])
            claim_b = claim_repo.get_full(pair["claim_b"])
        if claim_a is None or claim_b is None:
            return False

        try:
            call = classifier.screen(claim_a, claim_b, tier)
        except Exception as exc:  # noqa: BLE001 - one bad pair shouldn't sink the batch
            supervisor.note(f"screen failed for pair ({pair['claim_a']}, {pair['claim_b']}), skipped: {exc}")
            return False

        supervisor.spend("hunter", call.cost_usd)
        with get_connection() as conn:
            conflict_repo = ConflictRepository(conn)
            conflict_repo.mark_screened(
                pair["claim_a"], pair["claim_b"], call.result.is_candidate, call.result.reason
            )
            if call.result.is_candidate:
                conflict_repo.insert_candidate(pair["claim_a"], pair["claim_b"])
        if call.result.is_candidate:
            supervisor.note(f"CANDIDATE (similarity={pair['similarity']:.2f}): {call.result.reason}")
        return call.result.is_candidate


def main() -> None:
    parser = argparse.ArgumentParser(description="Find candidate contradiction pairs")
    parser.add_argument("--limit-pairs", type=int, default=200, help="max candidate pairs to screen")
    parser.add_argument("--workers", type=int, default=10, help="concurrent workers for embedding + screening")
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    stage_cfg = run_config.stages["hunter"]
    tier = run_config.models[stage_cfg.model_tier]
    supervisor = Supervisor(run_config, pipeline="hunter")
    embedder = EmbeddingClient()
    classifier = HunterClassifier()

    embedded = backfill_embeddings(supervisor, run_config, embedder, args.workers)
    supervisor.note(f"backfilled embeddings for {embedded} claims")
    # Repurposing "claims_added" as "embeddings backfilled" -- same pattern as
    # evals/llm_judge.py; Manifest's fields are generic enough for this.
    supervisor.increment("claims_added", embedded)

    with get_connection() as conn:
        pairs = ClaimRepository(conn).find_candidate_pairs(stage_cfg.top_k, stage_cfg.min_similarity)
    supervisor.note(
        f"{len(pairs)} candidate pairs from embedding blocking "
        f"(top_k={stage_cfg.top_k}, min_similarity={stage_cfg.min_similarity})"
    )
    pairs = pairs[: args.limit_pairs]  # highest-similarity first (SQL ORDER BY)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(screen_one, pair, tier, supervisor, classifier) for pair in pairs]
        flags = [f.result() for f in as_completed(futures)]
    screened = len(pairs)
    flagged = sum(1 for f in flags if f)

    manifest = supervisor.finalize()
    manifest.print_table()
    print(f"blocking found {len(pairs)} pairs, screened {screened}, flagged {flagged} as suspected conflicts")


if __name__ == "__main__":
    main()
