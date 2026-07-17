from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from openai import OpenAI

from dissonance.settings import settings
from dissonance.supervisor.config import EmbeddingConfig


@dataclass
class EmbeddingResult:
    vector: list[float]
    cost_usd: float


class EmbeddingClient:
    def __init__(self, client: Optional[OpenAI] = None):
        self._client = client or OpenAI(api_key=settings.openai_api_key)

    def embed(self, text: str, config: EmbeddingConfig) -> EmbeddingResult:
        response = self._client.embeddings.create(
            model=config.name, input=text, dimensions=config.dimensions
        )
        cost = response.usage.total_tokens / 1_000_000 * config.price_per_1m_input
        return EmbeddingResult(vector=response.data[0].embedding, cost_usd=cost)


def embedding_text(claim: dict) -> str:
    """What gets embedded -- assertion carries the most signal, subject/object
    anchor it to the specific comparison being made (so 'few-shot prompting
    increases GSM8K accuracy' blocks near other GSM8K/few-shot claims rather
    than just near other claims about accuracy in general)."""
    parts = [claim["assertion"], claim.get("subject") or "", claim.get("object") or ""]
    return " -- ".join(p for p in parts if p)
