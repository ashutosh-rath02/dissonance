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
