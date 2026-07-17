from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from dissonance.adjudicator.client import AdjudicationCall, AdjudicatorClient
from dissonance.adjudicator.consistency import rationale_contradicts_verdict
from dissonance.supervisor.config import RunConfig


@dataclass
class AdjudicationOutcome:
    type: Optional[str]
    verdict: str
    extraction_error_claim: Optional[str]
    rationale: str
    confidence: float
    cost_usd: float
    loops_used: int
    notes: list[str] = field(default_factory=list)


def adjudicate_pair(
    claim_a: dict, context_a: str, claim_b: dict, context_b: str,
    run_config: RunConfig, client: AdjudicatorClient,
) -> AdjudicationOutcome:
    """Tiered escalation loop (plan.md §4): start at tiers[0]; if confidence
    is below threshold, escalate to the next tier with the SAME context (more
    context wouldn't help -- a stronger model reading the same evidence
    might). A model that says "insufficient_context" itself is treated as a
    terminal answer, not escalated -- if the context is genuinely
    insufficient, a stronger model reading the identical context is unlikely
    to conjure missing information."""
    stage_cfg = run_config.stages["adjudicator"]
    tiers = stage_cfg.tiers or ["cheap"]
    max_tiers = min(stage_cfg.max_tiers or len(tiers), len(tiers))
    threshold = stage_cfg.confidence_threshold if stage_cfg.confidence_threshold is not None else 0.65

    total_cost = 0.0
    notes: list[str] = []
    last_call: Optional[AdjudicationCall] = None

    for tier_index in range(max_tiers):
        tier_name = tiers[tier_index]
        tier = run_config.models[tier_name]
        call = client.adjudicate(claim_a, context_a, claim_b, context_b, tier)
        total_cost += call.cost_usd
        last_call = call

        if rationale_contradicts_verdict(call.result.verdict, call.result.rationale):
            # The model's own reasoning undercuts its "genuine" verdict --
            # observed for real even after the rationale-before-verdict field
            # order fix (see dissonance/adjudicator/consistency.py). Treat
            # exactly like low confidence: escalate rather than trust it.
            notes.append(
                f"tier {tier_name} verdict 'genuine' contradicted by its own rationale, escalating"
            )
            continue

        if call.result.verdict == "insufficient_context" or call.result.confidence >= threshold:
            return AdjudicationOutcome(
                type=call.result.type,
                verdict=call.result.verdict,
                extraction_error_claim=call.result.extraction_error_claim,
                rationale=call.result.rationale,
                confidence=call.result.confidence,
                cost_usd=total_cost,
                loops_used=tier_index + 1,
                notes=notes,
            )
        notes.append(
            f"tier {tier_name} confidence {call.result.confidence:.2f} below threshold {threshold}, escalating"
        )

    # Exhausted every tier without reaching the confidence threshold, or the
    # last tier's "genuine" verdict was still self-contradictory -- either
    # way, don't trust it. insufficient_context is the honest fallback.
    assert last_call is not None  # max_tiers >= 1, so the loop ran at least once
    verdict = last_call.result.verdict
    rationale = last_call.result.rationale
    if rationale_contradicts_verdict(verdict, rationale):
        verdict = "insufficient_context"
        rationale = f"{rationale} [verdict was 'genuine' but contradicted its own rationale at every tier]"
    else:
        rationale = f"{rationale} [confidence below threshold at all {max_tiers} tier(s)]"
        verdict = "insufficient_context"
    return AdjudicationOutcome(
        type=last_call.result.type,
        verdict=verdict,
        extraction_error_claim=None,
        rationale=rationale,
        confidence=last_call.result.confidence,
        cost_usd=total_cost,
        loops_used=max_tiers,
        notes=notes,
    )
