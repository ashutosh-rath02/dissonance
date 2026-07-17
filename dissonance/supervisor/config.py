from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel


class ModelTierConfig(BaseModel):
    provider: str
    name: str
    max_output_tokens: int


class EscalationConfig(BaseModel):
    confidence_threshold: float
    consecutive_failures_to_escalate: int
    max_escalations: int


class StageConfig(BaseModel):
    model_tier: Optional[str] = None
    budget_usd: float = 0.0
    rate_limit_per_sec: Optional[float] = None
    max_retries: Optional[int] = None
    escalation: Optional[EscalationConfig] = None
    tiers: Optional[list[str]] = None
    max_tiers: Optional[int] = None


class RunSettings(BaseModel):
    budget_usd: float
    warn_at_fraction: float
    wall_clock_cap_seconds: int


class IdenticalFailureBreaker(BaseModel):
    max_repeats: int


class ReExtractionLoop(BaseModel):
    max_round_trips: int


class LoopsConfig(BaseModel):
    identical_failure_breaker: IdenticalFailureBreaker
    re_extraction: ReExtractionLoop


class CorpusConfig(BaseModel):
    domain: str
    cap_papers: int
    language: str


class RunConfig(BaseModel):
    run: RunSettings
    models: dict[str, ModelTierConfig]
    stages: dict[str, StageConfig]
    loops: LoopsConfig
    corpus: CorpusConfig

    @classmethod
    def load(cls, path: Path | str = "configs/run.yaml") -> "RunConfig":
        data = yaml.safe_load(Path(path).read_text())
        return cls.model_validate(data)
