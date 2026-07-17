from __future__ import annotations

import httpx
import feedparser

from dissonance.graph.models import Paper

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_PDF_LINK_TYPE = "application/pdf"


class ArxivScout:
    """Fetches paper metadata from the arXiv API (free, rate-limit aware).

    One request per call site; arXiv asks for >=3s between paginated requests,
    which callers doing multi-page fetches must respect (see `search_paginated`).
    """

    def __init__(self, client: httpx.Client | None = None):
        self._client = client or httpx.Client(timeout=30.0)

    def search(
        self,
        query: str,
        max_results: int = 50,
        start: int = 0,
        raw_query: bool = False,
        sort_by: str = "submittedDate",
    ) -> list[Paper]:
        """`query` is wrapped as `all:{query}` (a loose phrase match) unless
        `raw_query=True`, in which case it's passed straight through as
        arXiv's `search_query` -- lets callers use field-scoped, boolean
        queries like `cat:cs.CL AND (abs:benchmark OR abs:evaluation)`
        instead of one loose keyword phrase. `sort_by="relevance"` matters
        more than the default `submittedDate` for a broad or compound query:
        sorting by date just returns whatever was posted most recently that
        happens to match at all, not what best matches."""
        params = {
            "search_query": query if raw_query else f"all:{query}",
            "start": start,
            "max_results": max_results,
            "sortBy": sort_by,
            "sortOrder": "descending",
        }
        resp = self._client.get(ARXIV_API_URL, params=params)
        resp.raise_for_status()
        return self._parse_feed(resp.text)

    @staticmethod
    def _parse_feed(atom_xml: str) -> list[Paper]:
        feed = feedparser.parse(atom_xml)
        papers: list[Paper] = []
        for entry in feed.entries:
            arxiv_id = entry.id.rsplit("/abs/", 1)[-1]
            arxiv_id = arxiv_id.split("v")[0] if "v" in arxiv_id.rsplit("/", 1)[-1] else arxiv_id

            pdf_url = None
            for link in entry.get("links", []):
                if link.get("type") == ATOM_PDF_LINK_TYPE:
                    pdf_url = link.get("href")

            categories = [t["term"] for t in entry.get("tags", [])] if entry.get("tags") else []
            primary_category = entry.get("arxiv_primary_category", {}).get("term") if entry.get(
                "arxiv_primary_category"
            ) else (categories[0] if categories else None)

            papers.append(
                Paper(
                    paper_id=f"arxiv:{arxiv_id}",
                    arxiv_id=arxiv_id,
                    title=" ".join(entry.get("title", "").split()),
                    abstract=" ".join(entry.get("summary", "").split()) or None,
                    authors=[a["name"] for a in entry.get("authors", [])] if entry.get("authors") else [],
                    published_at=_parse_date(entry.get("published")),
                    updated_at=_parse_date(entry.get("updated")),
                    primary_category=primary_category,
                    categories=categories,
                    pdf_url=pdf_url,
                    # arXiv auto-generates HTML at this URL for most post-2023 submissions,
                    # but availability isn't guaranteed by the Atom feed -- extraction (Week 2)
                    # verifies by fetching it and downgrades full_text_status if it 404s.
                    html_url=f"https://arxiv.org/html/{arxiv_id}",
                    source="arxiv",
                    full_text_status="unknown",
                )
            )
        return papers

    def close(self) -> None:
        self._client.close()


def _parse_date(value: str | None):
    if not value:
        return None
    from datetime import datetime

    for fmt in ("%Y-%m-%dT%H:%M:%SZ",):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None
