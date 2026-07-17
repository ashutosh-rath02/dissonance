"""LLM-judge pass over extracted claims. `python -m evals.llm_judge --limit N`

NOT a substitute for human labeling. Judges whether each structured claim
faithfully represents its own verified source quote, storing results with
reviewer='llm_judge:<model>' in claim_labels -- distinguishable from
reviewer='human' at every point that reads this table (export_golden,
evals/report.py, the review UI dashboard). plan.md §5.1 defines the golden
set as independent human judgment; this is a disclosed, separate signal, not
a replacement for that pass.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from openai import OpenAI

from dissonance.extraction.fetch import fetch_full_text
from dissonance.graph.db import get_connection
from dissonance.graph.repository import LabelRepository, PaperRepository
from dissonance.settings import settings
from dissonance.supervisor.config import ModelTierConfig, RunConfig
from dissonance.supervisor.core import Supervisor
from evals.judge_schema import JudgeVerdict

PROMPT_VERSION = "judge_v1"
PROMPT_PATH = Path("configs/prompts") / f"{PROMPT_VERSION}.md"


@dataclass
class JudgeCall:
    result: JudgeVerdict
    cost_usd: float
    model: str


class JudgeClient:
    def __init__(self, client: Optional[OpenAI] = None):
        self._client = client or OpenAI(api_key=settings.openai_api_key)
        self._instructions = PROMPT_PATH.read_text()

    def judge(self, quote: str, claim: dict, tier: ModelTierConfig) -> JudgeCall:
        input_text = (
            f"Quote (verbatim from paper):\n{quote}\n\n"
            "Structured claim:\n"
            f"assertion: {claim['assertion']}\n"
            f"subject: {claim['subject']}\n"
            f"object: {claim['object']}\n"
            f"direction: {claim['direction']}\n"
            f"effect_size: {claim['effect_size']}\n"
            f"conditions: {claim['conditions']}\n"
            f"method_type: {claim['method_type']}\n"
            f"evidence_strength: {claim['evidence_strength']}\n"
        )
        response = self._client.responses.parse(
            model=tier.name,
            instructions=self._instructions,
            input=input_text,
            text_format=JudgeVerdict,
            max_output_tokens=tier.max_output_tokens,
        )
        usage = response.usage
        cost = (
            usage.input_tokens / 1_000_000 * tier.price_per_1m_input
            + usage.output_tokens / 1_000_000 * tier.price_per_1m_output
        )
        return JudgeCall(result=response.output_parsed, cost_usd=cost, model=tier.name)


def judge_one(claim: dict, quote: Optional[str], judge: JudgeClient, tier: ModelTierConfig) -> tuple[JudgeVerdict, float]:
    """Pure-ish wrapper: no source text -> uncertain, no API call, no cost."""
    if quote is None:
        return JudgeVerdict(verdict="uncertain", rationale="source text unavailable, cannot verify against quote"), 0.0
    call = judge.judge(quote, claim, tier)
    return call.result, call.cost_usd


def main() -> None:
    parser = argparse.ArgumentParser(description="LLM-judge review of extracted claims")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--config", default="configs/run.yaml")
    args = parser.parse_args()

    run_config = RunConfig.load(args.config)
    stage_cfg = run_config.stages["judge"]
    tier = run_config.models[stage_cfg.model_tier]
    supervisor = Supervisor(run_config, pipeline="llm_judge")
    judge = JudgeClient()
    reviewer = f"llm_judge:{tier.name}"

    with get_connection() as conn:
        claims = LabelRepository(conn).claims_needing_review(args.limit)
    supervisor.note(f"{len(claims)} unlabeled claims found")

    text_cache: dict[str, Optional[str]] = {}
    fetch_failed: set[str] = set()  # paper_ids whose fetch errored THIS run -- retry later, don't fake-label

    for claim in claims:
        if supervisor.budget.halted:
            supervisor.note(f"budget halted, stopping before claim {claim['claim_id']}")
            break

        with supervisor.stage("judge"):
            paper_id = claim["paper_id"]
            if paper_id in fetch_failed:
                continue  # skip silently -- already noted when the fetch failed

            if paper_id not in text_cache:
                with get_connection() as conn:
                    paper = PaperRepository(conn).get(paper_id)
                try:
                    fetched = fetch_full_text(paper["html_url"], paper.get("abstract")) if paper else None
                except Exception as exc:  # noqa: BLE001 - transient network error, same class fixed in
                    # dissonance/extraction/pipeline.py. A network blip isn't a real
                    # judgment -- skip this paper's claims this run (leave unlabeled
                    # for a later run) rather than recording a fake "uncertain" verdict.
                    supervisor.note(f"{paper_id}: fetch failed, skipping this run: {exc}")
                    fetch_failed.add(paper_id)
                    continue
                text_cache[paper_id] = fetched.text if fetched else None
            text = text_cache[paper_id]

            quote = None
            if text is not None:
                span = claim["source_span"]
                quote = text[span["char_start"] : span["char_end"]]

            try:
                verdict, cost = judge_one(claim, quote, judge, tier)
            except Exception as exc:  # noqa: BLE001 - one bad claim shouldn't sink the batch
                supervisor.note(f"{claim['claim_id']}: judge call failed, skipped: {exc}")
                continue

            supervisor.spend("judge", cost)
            with get_connection() as conn:
                LabelRepository(conn).upsert(
                    str(claim["claim_id"]), verdict.verdict, verdict.rationale, reviewer=reviewer
                )
            # Repurposing "claims_added" as "claims judged" for this pipeline --
            # Manifest's fields are generic enough and this keeps one schema.
            supervisor.increment("claims_added", 1)
            supervisor.note(f"{claim['claim_id']}: {verdict.verdict} -- {verdict.rationale}")

    manifest = supervisor.finalize()
    manifest.print_table()


if __name__ == "__main__":
    main()
