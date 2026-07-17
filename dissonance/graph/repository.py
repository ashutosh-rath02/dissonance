from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection
from psycopg.types.json import Jsonb

from dissonance.graph.models import Paper


@dataclass
class UpsertResult:
    touched: int
    new: int


class PaperRepository:
    def __init__(self, conn: Connection):
        self._conn = conn

    def upsert_many(self, papers: list[Paper]) -> UpsertResult:
        new_count = 0
        with self._conn.cursor() as cur:
            for p in papers:
                cur.execute("SELECT 1 FROM papers WHERE paper_id = %s", (p.paper_id,))
                is_new = cur.fetchone() is None
                cur.execute(
                    """
                    INSERT INTO papers (
                        paper_id, arxiv_id, doi, title, abstract, authors,
                        published_at, updated_at, primary_category, categories,
                        pdf_url, html_url, source, full_text_status
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (paper_id) DO UPDATE SET
                        title = EXCLUDED.title,
                        abstract = EXCLUDED.abstract,
                        updated_at = EXCLUDED.updated_at,
                        full_text_status = EXCLUDED.full_text_status
                    """,
                    (
                        p.paper_id, p.arxiv_id, p.doi, p.title, p.abstract, p.authors,
                        p.published_at, p.updated_at, p.primary_category, p.categories,
                        p.pdf_url, p.html_url, p.source, p.full_text_status,
                    ),
                )
                if is_new:
                    new_count += 1
        return UpsertResult(touched=len(papers), new=new_count)

    def papers_needing_extraction(self, limit: int) -> list[dict]:
        """Papers not yet extracted (pending) and not quarantined, oldest-ingested first."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT paper_id, title, abstract, html_url
                FROM papers
                WHERE extraction_status = 'pending'
                ORDER BY ingested_at ASC
                LIMIT %s
                """,
                (limit,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def update_full_text_status(self, paper_id: str, status: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE papers SET full_text_status = %s WHERE paper_id = %s",
                (status, paper_id),
            )

    def update_extraction_status(self, paper_id: str, status: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                "UPDATE papers SET extraction_status = %s WHERE paper_id = %s",
                (status, paper_id),
            )

    def list_with_stats(self, limit: int = 200, offset: int = 0) -> list[dict]:
        """For the review UI dashboard: one row per paper with claim/label
        counts. human_labeled_count and llm_labeled_count are kept separate,
        not merged, so the dashboard can never display an LLM-judge pass as
        if it were human review coverage."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.paper_id, p.title, p.extraction_status, p.full_text_status,
                       count(c.claim_id) AS claim_count,
                       count(l.claim_id) FILTER (WHERE l.reviewer = 'human') AS human_labeled_count,
                       count(l.claim_id) FILTER (WHERE l.reviewer <> 'human') AS llm_labeled_count
                FROM papers p
                LEFT JOIN claims c ON c.paper_id = p.paper_id
                LEFT JOIN claim_labels l ON l.claim_id = c.claim_id
                GROUP BY p.paper_id, p.title, p.extraction_status, p.full_text_status
                ORDER BY p.ingested_at ASC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get(self, paper_id: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT paper_id, title, abstract, authors, primary_category, html_url,
                       pdf_url, source, full_text_status, extraction_status
                FROM papers WHERE paper_id = %s
                """,
                (paper_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))


class ClaimRepository:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert_claims(self, claims: list[dict]) -> int:
        with self._conn.cursor() as cur:
            for c in claims:
                cur.execute(
                    """
                    INSERT INTO claims (
                        claim_id, paper_id, assertion, subject, object, direction,
                        effect_size, conditions, method_type, evidence_strength,
                        source_span, extraction_confidence, extracted_by
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        c["claim_id"], c["paper_id"], c["assertion"], c["subject"], c["object"],
                        c["direction"], Jsonb(c["effect_size"]), Jsonb(c["conditions"]),
                        c["method_type"], c["evidence_strength"], Jsonb(c["source_span"]),
                        c["extraction_confidence"], Jsonb(c["extracted_by"]),
                    ),
                )
        return len(claims)

    def list_for_paper(self, paper_id: str) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.claim_id, c.paper_id, c.assertion, c.subject, c.object, c.direction,
                       c.effect_size, c.conditions, c.method_type, c.evidence_strength,
                       c.source_span, c.extraction_confidence, c.extracted_by,
                       l.verdict AS label_verdict, l.notes AS label_notes, l.reviewer AS label_reviewer
                FROM claims c
                LEFT JOIN claim_labels l ON l.claim_id = c.claim_id
                WHERE c.paper_id = %s
                ORDER BY c.created_at ASC
                """,
                (paper_id,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get(self, claim_id: str) -> dict | None:
        with self._conn.cursor() as cur:
            cur.execute("SELECT claim_id, paper_id FROM claims WHERE claim_id = %s", (claim_id,))
            row = cur.fetchone()
            return {"claim_id": row[0], "paper_id": row[1]} if row else None

    def list_all(self) -> list[dict]:
        """Every claim in the graph, for corpus-wide checks (e.g. citation
        faithfulness) that don't need human labels -- just the stored span."""
        with self._conn.cursor() as cur:
            cur.execute("SELECT claim_id, paper_id, source_span FROM claims ORDER BY paper_id")
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def claims_missing_embeddings(self, limit: int) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT claim_id, paper_id, assertion, subject, object
                FROM claims WHERE embedding IS NULL
                ORDER BY created_at LIMIT %s
                """,
                (limit,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def update_embedding(self, claim_id: str, vector: list[float]) -> None:
        with self._conn.cursor() as cur:
            cur.execute("UPDATE claims SET embedding = %s WHERE claim_id = %s", (vector, claim_id))

    def find_candidate_pairs(self, top_k: int, min_similarity: float) -> list[dict]:
        """Cross-paper nearest neighbors by cosine similarity -- the embedding
        blocking step (plan.md §3.1). Same-paper claims are excluded: the
        contradiction-hunting differentiator is finding conflicts between
        papers that never cite each other, not within one paper. Returns each
        unordered pair once (claim_id_1 < claim_id_2 as text, arbitrary but
        stable, just for de-duplication)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                WITH neighbors AS (
                    SELECT a.claim_id AS claim_a, b.claim_id AS claim_b,
                           1 - (a.embedding <=> b.embedding) AS similarity,
                           row_number() OVER (
                               PARTITION BY a.claim_id ORDER BY a.embedding <=> b.embedding
                           ) AS rank
                    FROM claims a
                    JOIN claims b ON b.paper_id <> a.paper_id AND b.embedding IS NOT NULL
                    WHERE a.embedding IS NOT NULL
                )
                SELECT LEAST(claim_a, claim_b) AS claim_a, GREATEST(claim_a, claim_b) AS claim_b,
                       max(similarity) AS similarity
                FROM neighbors
                WHERE rank <= %s AND similarity >= %s
                GROUP BY LEAST(claim_a, claim_b), GREATEST(claim_a, claim_b)
                ORDER BY similarity DESC
                """,
                (top_k, min_similarity),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def get_full(self, claim_id: str) -> dict | None:
        """Full claim row (all fields) -- for the adjudicator, which needs
        every structured field, not just the id/paper_id `get()` returns."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT claim_id, paper_id, assertion, subject, object, direction,
                       effect_size, conditions, method_type, evidence_strength, source_span
                FROM claims WHERE claim_id = %s
                """,
                (claim_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d.name for d in cur.description]
            return dict(zip(cols, row))

    def delete(self, claim_id: str) -> None:
        """Re-extraction loop (plan.md §4): adjudicator verdict =
        extraction_error -> delete the bad claim, caller re-queues its paper."""
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM claims WHERE claim_id = %s", (claim_id,))


class LabelRepository:
    def __init__(self, conn: Connection):
        self._conn = conn

    def upsert(self, claim_id: str, verdict: str, notes: str | None, reviewer: str = "human") -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO claim_labels (claim_id, verdict, notes, reviewer, labeled_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (claim_id) DO UPDATE SET
                    verdict = EXCLUDED.verdict, notes = EXCLUDED.notes,
                    reviewer = EXCLUDED.reviewer, labeled_at = now()
                """,
                (claim_id, verdict, notes, reviewer),
            )

    def claims_needing_review(self, limit: int) -> list[dict]:
        """Claims with no label at all yet (any reviewer) -- what evals/llm_judge.py pulls."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.claim_id, c.paper_id, c.assertion, c.subject, c.object, c.direction,
                       c.effect_size, c.conditions, c.method_type, c.evidence_strength,
                       c.source_span, c.extraction_confidence
                FROM claims c
                LEFT JOIN claim_labels l ON l.claim_id = c.claim_id
                WHERE l.claim_id IS NULL
                ORDER BY c.paper_id, c.created_at
                LIMIT %s
                """,
                (limit,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def export_golden(self, reviewer: str = "human") -> list[dict]:
        """Claims labeled 'correct' by `reviewer`, shaped like plan.md §3.2's
        Claim schema -- this is the evals/golden/ export the eval harness
        (Week 3) consumes. Defaults to 'human' because plan.md §5.1 defines
        the golden set as independent human judgment; callers must opt in
        explicitly to export an LLM-judge reviewer instead."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.claim_id, c.paper_id, c.assertion, c.subject, c.object, c.direction,
                       c.effect_size, c.conditions, c.method_type, c.evidence_strength,
                       c.source_span, c.extraction_confidence, c.extracted_by
                FROM claims c
                JOIN claim_labels l ON l.claim_id = c.claim_id
                WHERE l.verdict = 'correct' AND l.reviewer = %s
                ORDER BY c.paper_id, c.created_at
                """,
                (reviewer,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def verdict_counts(self, reviewer: str | None = None) -> dict[str, int]:
        with self._conn.cursor() as cur:
            if reviewer is None:
                cur.execute("SELECT verdict, count(*) FROM claim_labels GROUP BY verdict")
            else:
                cur.execute(
                    "SELECT verdict, count(*) FROM claim_labels WHERE reviewer = %s GROUP BY verdict",
                    (reviewer,),
                )
            return dict(cur.fetchall())

    def reviewer_counts(self) -> dict[str, int]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT reviewer, count(*) FROM claim_labels GROUP BY reviewer")
            return dict(cur.fetchall())

    def export_review_log(self, reviewer: str | None = None) -> list[dict]:
        """Every labeled claim regardless of verdict -- the denominator
        `claims.json` (correct-only) lacks. This is what makes precision
        computable: correct / (correct + incorrect). Pass `reviewer` to
        restrict to one reviewer; None returns all (human + LLM-judge mixed --
        callers must not treat that mix as a single "ground truth" number)."""
        with self._conn.cursor() as cur:
            if reviewer is None:
                cur.execute(
                    """
                    SELECT l.claim_id, c.paper_id, l.verdict, l.notes, l.reviewer, l.labeled_at
                    FROM claim_labels l
                    JOIN claims c ON c.claim_id = l.claim_id
                    ORDER BY l.labeled_at
                    """,
                )
            else:
                cur.execute(
                    """
                    SELECT l.claim_id, c.paper_id, l.verdict, l.notes, l.reviewer, l.labeled_at
                    FROM claim_labels l
                    JOIN claims c ON c.claim_id = l.claim_id
                    WHERE l.reviewer = %s
                    ORDER BY l.labeled_at
                    """,
                    (reviewer,),
                )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]


class ConflictRepository:
    def __init__(self, conn: Connection):
        self._conn = conn

    def insert_candidate(self, claim_a: str, claim_b: str) -> None:
        """Hunter output: an unadjudicated candidate pair (type/verdict NULL
        until the adjudicator runs). ON CONFLICT DO NOTHING makes re-running
        blocking idempotent -- see idx_conflicts_claim_pair in schema.sql."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conflicts (claim_a, claim_b)
                VALUES (%s, %s)
                ON CONFLICT (claim_a, claim_b) DO NOTHING
                """,
                (claim_a, claim_b),
            )

    def needing_adjudication(self, limit: int) -> list[dict]:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT conflict_id, claim_a, claim_b
                FROM conflicts
                WHERE verdict IS NULL
                ORDER BY created_at
                LIMIT %s
                """,
                (limit,),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def update_verdict(
        self,
        conflict_id: str,
        *,
        type_: str,
        verdict: str,
        rationale: str,
        confidence: float,
        cost_usd: float,
        loops_used: int,
        status: str = "open",
    ) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                UPDATE conflicts SET
                    type = %s, verdict = %s, adjudicator_rationale = %s, confidence = %s,
                    adjudication_cost_usd = %s, loops_used = %s, status = %s
                WHERE conflict_id = %s
                """,
                (type_, verdict, rationale, confidence, cost_usd, loops_used, status, conflict_id),
            )

    def delete(self, conflict_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute("DELETE FROM conflicts WHERE conflict_id = %s", (conflict_id,))

    def verdict_counts(self) -> dict[str, int]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT verdict, count(*) FROM conflicts WHERE verdict IS NOT NULL GROUP BY verdict"
            )
            return dict(cur.fetchall())
