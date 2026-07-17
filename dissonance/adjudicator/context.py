from __future__ import annotations

WINDOW_CHARS = 500  # each side of the verified span


def context_window(text: str, span: dict, window: int = WINDOW_CHARS) -> str:
    """Full-text context around a claim's verified span (plan.md §3.1: the
    adjudicator "pulls full-text context for both claims", not just the bare
    extracted quote)."""
    start = max(0, span["char_start"] - window)
    end = min(len(text), span["char_end"] + window)
    return text[start:end]
