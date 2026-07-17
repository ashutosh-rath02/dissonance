from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class JudgeVerdict(BaseModel):
    # `rationale` first -- same reasoning-before-answer fix as
    # dissonance/adjudicator/schema.py's AdjudicatorVerdict (found there
    # first: verdicts whose own rationale said "no contradiction" but were
    # stored as "genuine", because structured outputs fill fields in
    # declaration order and `verdict` was written before the reasoning that's
    # supposed to justify it). This schema had the identical bug -- the
    # Week 3 62% LLM-judge precision number was measured before this fix and
    # should be treated as unreliable; see CLAUDE.md.
    rationale: str
    verdict: Literal["correct", "incorrect", "uncertain"]
