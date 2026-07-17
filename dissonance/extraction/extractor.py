from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from dissonance.extraction.schema import ExtractionResult
from dissonance.settings import settings
from dissonance.supervisor.config import ModelTierConfig

PROMPT_VERSION = "extraction_v1"
PROMPT_PATH = Path("configs/prompts") / f"{PROMPT_VERSION}.md"


@dataclass
class ExtractionCall:
    result: ExtractionResult
    cost_usd: float
    model: str


class Extractor:
    """Wraps the OpenAI Responses API structured-output call. `error_note`
    lets the extraction retry loop (dissonance/extraction/run.py) inject the
    previous attempt's validation failure back into the prompt, per plan.md
    §4's "retry with validator error injected" policy."""

    def __init__(self, client: OpenAI | None = None):
        self._client = client or OpenAI(api_key=settings.openai_api_key)
        self._instructions = PROMPT_PATH.read_text()

    def extract(
        self,
        paper_title: str,
        text: str,
        tier: ModelTierConfig,
        error_note: str | None = None,
    ) -> ExtractionCall:
        input_text = f"Paper title: {paper_title}\n\nText:\n{text}"
        if error_note:
            input_text += f"\n\nYour previous attempt was invalid: {error_note}\nFix it and try again."

        response = self._client.responses.parse(
            model=tier.name,
            instructions=self._instructions,
            input=input_text,
            text_format=ExtractionResult,
            max_output_tokens=tier.max_output_tokens,
        )
        usage = response.usage
        cost = (
            usage.input_tokens / 1_000_000 * tier.price_per_1m_input
            + usage.output_tokens / 1_000_000 * tier.price_per_1m_output
        )
        return ExtractionCall(result=response.output_parsed, cost_usd=cost, model=tier.name)
