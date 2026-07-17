from __future__ import annotations

from pydantic import BaseModel


class HunterScreen(BaseModel):
    is_candidate: bool
    reason: str
