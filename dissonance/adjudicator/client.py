from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openai import OpenAI

from dissonance.adjudicator.schema import AdjudicatorVerdict
from dissonance.settings import settings
from dissonance.supervisor.config import ModelTierConfig

PROMPT_VERSION = "adjudicator_v1"
PROMPT_PATH = Path("configs/prompts") / f"{PROMPT_VERSION}.md"


@dataclass
class AdjudicationCall:
    result: AdjudicatorVerdict
    cost_usd: float
    model: str


def _describe(claim: dict, context: str) -> str:
    return (
        f"assertion: {claim['assertion']}\n"
        f"subject: {claim['subject']}\n"
        f"object: {claim['object']}\n"
        f"direction: {claim['direction']}\n"
        f"effect_size: {claim['effect_size']}\n"
        f"conditions: {claim['conditions']}\n\n"
        f"Context from the paper around this claim's source:\n{context}\n"
    )


class AdjudicatorClient:
    def __init__(self, client: Optional[OpenAI] = None):
        self._client = client or OpenAI(api_key=settings.openai_api_key)
        self._instructions = PROMPT_PATH.read_text()

    def adjudicate(
        self, claim_a: dict, context_a: str, claim_b: dict, context_b: str, tier: ModelTierConfig
    ) -> AdjudicationCall:
        input_text = (
            f"Claim A (paper {claim_a['paper_id']}):\n{_describe(claim_a, context_a)}\n"
            f"Claim B (paper {claim_b['paper_id']}):\n{_describe(claim_b, context_b)}\n"
        )
        response = self._client.responses.parse(
            model=tier.name,
            instructions=self._instructions,
            input=input_text,
            text_format=AdjudicatorVerdict,
            max_output_tokens=tier.max_output_tokens,
        )
        usage = response.usage
        cost = (
            usage.input_tokens / 1_000_000 * tier.price_per_1m_input
            + usage.output_tokens / 1_000_000 * tier.price_per_1m_output
        )
        return AdjudicationCall(result=response.output_parsed, cost_usd=cost, model=tier.name)
