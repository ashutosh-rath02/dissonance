from __future__ import annotations

from dataclasses import dataclass

from psycopg import Connection

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
