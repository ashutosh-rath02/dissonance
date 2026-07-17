from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openai import OpenAI

from dissonance.hunter.schema import HunterScreen
from dissonance.settings import settings
from dissonance.supervisor.config import ModelTierConfig

PROMPT_VERSION = "hunter_v1"
PROMPT_PATH = Path("configs/prompts") / f"{PROMPT_VERSION}.md"


@dataclass
class ScreenCall:
    result: HunterScreen
    cost_usd: float


def _describe(claim: dict) -> str:
    return (
        f"assertion: {claim['assertion']}\n"
        f"subject: {claim['subject']}\n"
        f"object: {claim['object']}\n"
        f"direction: {claim['direction']}\n"
        f"effect_size: {claim['effect_size']}\n"
        f"conditions: {claim['conditions']}\n"
        f"method_type: {claim['method_type']}\n"
    )


class HunterClassifier:
    def __init__(self, client: Optional[OpenAI] = None):
        self._client = client or OpenAI(api_key=settings.openai_api_key)
        self._instructions = PROMPT_PATH.read_text()

    def screen(self, claim_a: dict, claim_b: dict, tier: ModelTierConfig) -> ScreenCall:
        input_text = f"Claim A (paper {claim_a['paper_id']}):\n{_describe(claim_a)}\n" \
                     f"Claim B (paper {claim_b['paper_id']}):\n{_describe(claim_b)}\n"
        response = self._client.responses.parse(
            model=tier.name,
            instructions=self._instructions,
            input=input_text,
            text_format=HunterScreen,
            max_output_tokens=tier.max_output_tokens,
        )
        usage = response.usage
        cost = (
            usage.input_tokens / 1_000_000 * tier.price_per_1m_input
            + usage.output_tokens / 1_000_000 * tier.price_per_1m_output
        )
        return ScreenCall(result=response.output_parsed, cost_usd=cost)
