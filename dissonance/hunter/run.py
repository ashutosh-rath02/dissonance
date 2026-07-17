"""Contradiction hunter: embedding blocking + cheap classifier -> suspected conflicts.

    python -m dissonance.hunter.run --limit-pairs 200

Backfills any missing claim embeddings, finds cross-paper candidate pairs by
cosine similarity (plan.md §3.1's "embedding blocking"), then runs a cheap
classifier over each candidate to filter out pairs that are only
superficially similar. Flagged pairs land in `conflicts` with verdict=NULL,
ready for `python -m dissonance.adjudicator.run`.
"""

from __future__ import annotations

import argparse

from dissonance.graph.db import get_connection
from dissonance.graph.repository import ClaimRepository, ConflictRepository
from dissonance.hunter.classifier import HunterClassifier
from dissonance.hunter.embeddings import EmbeddingClient, embedding_text
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.core import Supervisor


def backfill_embeddings(supervisor: Supervisor, run_config: RunConfig, embedder: EmbeddingClient) -> int:
    count = 0
    while True:
        with get_connection() as conn:
            claims = ClaimRepository(conn).claims_missing_embeddings(50)
        if not claims:
            break
        for claim in claims:
            if supervisor.budget.halted:
                return count
            with supervisor.stage("hunter"):
                result = embedder.embed(embedding_text(claim), run_config.embedding)
                supervisor.spend("hunter", result.cost_usd)
                with get_connection() as conn:
                    ClaimRepository(conn).update_embedding(str(claim["claim_id"]), result.vector)
                count += 1
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Find candidate contradiction pairs")
    parser.add_argument("--limit-pairs", type=int, default=200, help="max candidate pairs to screen")
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    stage_cfg = run_config.stages["hunter"]
    tier = run_config.models[stage_cfg.model_tier]
    supervisor = Supervisor(run_config, pipeline="hunter")
    embedder = EmbeddingClient()
    classifier = HunterClassifier()

    embedded = backfill_embeddings(supervisor, run_config, embedder)
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

    flagged = 0
    screened = 0
    for pair in pairs:
        if supervisor.budget.halted:
            supervisor.note("budget halted, stopping pair screening")
            break
        with supervisor.stage("hunter"):
            with get_connection() as conn:
                claim_repo = ClaimRepository(conn)
                claim_a = claim_repo.get_full(pair["claim_a"])
                claim_b = claim_repo.get_full(pair["claim_b"])
            if claim_a is None or claim_b is None:
                continue

            try:
                call = classifier.screen(claim_a, claim_b, tier)
            except Exception as exc:  # noqa: BLE001 - one bad pair shouldn't sink the batch
                supervisor.note(f"screen failed for pair ({pair['claim_a']}, {pair['claim_b']}), skipped: {exc}")
                continue

            screened += 1
            supervisor.spend("hunter", call.cost_usd)
            with get_connection() as conn:
                conflict_repo = ConflictRepository(conn)
                conflict_repo.mark_screened(
                    pair["claim_a"], pair["claim_b"], call.result.is_candidate, call.result.reason
                )
                if call.result.is_candidate:
                    conflict_repo.insert_candidate(pair["claim_a"], pair["claim_b"])
            if call.result.is_candidate:
                flagged += 1
                supervisor.note(f"CANDIDATE (similarity={pair['similarity']:.2f}): {call.result.reason}")

    manifest = supervisor.finalize()
    manifest.print_table()
    print(f"blocking found {len(pairs)} pairs, screened {screened}, flagged {flagged} as suspected conflicts")


if __name__ == "__main__":
    main()
