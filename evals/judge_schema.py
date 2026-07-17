from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class JudgeVerdict(BaseModel):
    verdict: Literal["correct", "incorrect", "uncertain"]
    rationale: str
