# ADR 0003: Postgres + pgvector, single instance

## Status
Accepted (2026-07-17)

## Context
Claims, papers, conflicts, and claim embeddings (for contradiction-hunter blocking, plan.md §3.1)
all need to live somewhere queryable by both relational joins (paper ↔ claim ↔ conflict) and
vector similarity (embedding neighborhoods).

## Decision
Single Postgres instance with the `pgvector` extension (`pgvector/pgvector:pg16` image), rather
than a separate vector store (Pinecone/Qdrant/Weaviate) alongside a relational database.

## Rationale
- The claim graph's core operations are relational (a conflict is a foreign-key pair of claims,
  a claim belongs to a paper) with one vector-similarity step (blocking candidate pairs). Splitting
  that across two databases means every hunter query becomes a join across two systems.
- One `docker-compose up` for local dev and CI; no second service, no sync problem between the
  relational and vector stores.
- 300-500 papers × ~5-10 claims each ≈ 1.5k-5k embeddings for v1 — nowhere near the scale where
  pgvector's IVFFlat/HNSW indexes stop being competitive with a dedicated vector DB.

## Consequences
- If corpus scale grows by 100x+ post-v1 (stretch goal: second domain), revisit — pgvector's
  approximate-search indexes degrade at very large scale compared to purpose-built vector DBs.
- Schema lives in `dissonance/graph/schema.sql`, applied via `python -m dissonance.graph.migrate`.
