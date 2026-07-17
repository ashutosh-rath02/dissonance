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
        """For the review UI dashboard: one row per paper with claim/label counts."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.paper_id, p.title, p.extraction_status, p.full_text_status,
                       count(c.claim_id) AS claim_count,
                       count(l.claim_id) AS labeled_count
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
                       l.verdict AS label_verdict, l.notes AS label_notes
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


class LabelRepository:
    def __init__(self, conn: Connection):
        self._conn = conn

    def upsert(self, claim_id: str, verdict: str, notes: str | None) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO claim_labels (claim_id, verdict, notes, labeled_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (claim_id) DO UPDATE SET
                    verdict = EXCLUDED.verdict, notes = EXCLUDED.notes, labeled_at = now()
                """,
                (claim_id, verdict, notes),
            )

    def export_golden(self) -> list[dict]:
        """Claims labeled 'correct', shaped like plan.md §3.2's Claim schema --
        this is the evals/golden/ export the eval harness (Week 3) consumes."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.claim_id, c.paper_id, c.assertion, c.subject, c.object, c.direction,
                       c.effect_size, c.conditions, c.method_type, c.evidence_strength,
                       c.source_span, c.extraction_confidence, c.extracted_by
                FROM claims c
                JOIN claim_labels l ON l.claim_id = c.claim_id
                WHERE l.verdict = 'correct'
                ORDER BY c.paper_id, c.created_at
                """,
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def verdict_counts(self) -> dict[str, int]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT verdict, count(*) FROM claim_labels GROUP BY verdict")
            return dict(cur.fetchall())

    def export_review_log(self) -> list[dict]:
        """Every labeled claim regardless of verdict -- the denominator
        `claims.json` (correct-only) lacks. This is what makes precision
        computable: correct / (correct + incorrect)."""
        with self._conn.cursor() as cur:
            cur.execute(
                """
                SELECT l.claim_id, c.paper_id, l.verdict, l.notes, l.labeled_at
                FROM claim_labels l
                JOIN claims c ON c.claim_id = l.claim_id
                ORDER BY l.labeled_at
                """,
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]
