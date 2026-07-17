from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx
from bs4 import BeautifulSoup

FullTextStatus = Literal["html_available", "pdf_only", "abstract_only", "unknown"]

# arXiv's HTML export drops these boilerplate sections; keep the body only.
# `annotation`/`annotation-xml` are LaTeXML's hidden TeX-source duplicates of
# rendered MathML (e.g. a visible "12.4%" is followed by a hidden
# "12.4\%" annotation) -- get_text() would otherwise concatenate both,
# corrupting every sentence containing math or a formatted number.
_STRIP_TAGS = ("script", "style", "nav", "header", "footer", "annotation", "annotation-xml")


@dataclass
class FetchResult:
    text: str | None
    status: FullTextStatus


def fetch_full_text(html_url: str, abstract: str | None, client: httpx.Client | None = None) -> FetchResult:
    """Try arXiv's auto-generated HTML; fall back to abstract-only.

    PDF fallback (GROBID/marker, plan.md §6) is out of scope for v1 -- if HTML
    isn't available we flag abstract_only rather than silently degrading
    (plan.md §2).
    """
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        resp = client.get(html_url)
        if resp.status_code != 200:
            return FetchResult(text=abstract, status="abstract_only" if abstract else "unknown")

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(_STRIP_TAGS):
            tag.decompose()
        text = " ".join(soup.get_text(separator=" ").split())
        if not text:
            return FetchResult(text=abstract, status="abstract_only" if abstract else "unknown")
        return FetchResult(text=text, status="html_available")
    finally:
        if owns_client:
            client.close()
