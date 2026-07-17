from __future__ import annotations

from pydantic import BaseModel


class HunterScreen(BaseModel):
    # `reason` first -- same reasoning-before-answer fix as
    # dissonance/adjudicator/schema.py's AdjudicatorVerdict. Structured
    # outputs fill fields in declaration order; deciding `is_candidate`
    # before writing `reason` lets the two drift apart.
    reason: str
    is_candidate: bool
