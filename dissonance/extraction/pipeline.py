from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from dissonance.extraction.extractor import PROMPT_VERSION, Extractor
from dissonance.extraction.fetch import fetch_full_text
from dissonance.extraction.validator import SpanNotFoundError, build_claim_record
from dissonance.graph.entity_resolution import normalize
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.exceptions import IdenticalFailureBreakerTripped


@dataclass
class PaperExtractionOutcome:
    claim_records: list[dict]
    full_text_status: str
    extraction_status: str  # "done" | "quarantined" | "pending" (transient failure, retry later)
    attempts: int
    cost_usd: float
    notes: list[str] = field(default_factory=list)


def extract_paper(paper: dict, run_config: RunConfig, extractor: Extractor, run_id: str) -> PaperExtractionOutcome:
    """Runs the retry-with-validator-feedback / confidence-escalation loop
    (plan.md §4) for a single paper. No I/O beyond the extractor and fetch
    calls -- kept pure-ish so it's unit-testable without a database."""
    stage_cfg = run_config.stages["extraction"]
    tier_name = stage_cfg.model_tier or "cheap"

    try:
        fetched = fetch_full_text(paper["html_url"], paper.get("abstract"))
    except Exception as exc:  # noqa: BLE001 - transient network/DNS errors, not a data problem
        # Leave the paper "pending" (not "quarantined") so a later run retries
        # it -- a DNS blip fetching one paper shouldn't discard 40 others'
        # worth of budget in the same run (this crashed the whole batch before
        # this fix; caught live during Week 3 corpus extraction).
        return PaperExtractionOutcome([], "unknown", "pending", 0, 0.0, [f"fetch failed, left pending for retry: {exc}"])

    if not fetched.text:
        return PaperExtractionOutcome([], fetched.status, "quarantined", 0, 0.0, ["no text available"])

    signature_counts: dict[str, int] = {}
    error_note: str | None = None
    consecutive_low_confidence = 0
    escalated = False
    total_cost = 0.0
    notes: list[str] = []
    max_repeats = run_config.loops.identical_failure_breaker.max_repeats

    def bump(signature: str) -> None:
        signature_counts[signature] = signature_counts.get(signature, 0) + 1
        if signature_counts[signature] >= max_repeats:
            raise IdenticalFailureBreakerTripped(signature, signature_counts[signature])

    for attempt in range(1, stage_cfg.max_retries + 1):
        try:
            call = extractor.extract(paper["title"], fetched.text, run_config.models[tier_name], error_note=error_note)
        except IdenticalFailureBreakerTripped:
            raise
        except Exception as exc:  # noqa: BLE001 - any API failure is retryable here
            bump(f"api_error:{type(exc).__name__}")
            error_note = f"API error: {exc}"
            continue

        total_cost += call.cost_usd
        records: list[dict] = []
        last_span_error: str | None = None
        for extracted in call.result.claims:
            try:
                record = build_claim_record(
                    paper_id=paper["paper_id"], claim=extracted, source_text=fetched.text,
                    model=call.model, prompt_version=PROMPT_VERSION, run_id=run_id,
                )
            except SpanNotFoundError as exc:
                # A single bad quote (e.g. the model eliding two sentences with
                # "...") shouldn't discard every other valid claim in the same
                # batch -- drop just this one and keep going. Signature includes
                # the quote so genuinely different failures each consume normal
                # retry budget; only the model repeating the *exact same* bad
                # quote trips the breaker early.
                bump(f"span_not_found:{exc.quote[:60]}")
                last_span_error = str(exc)
                notes.append(f"dropped claim with unverifiable quote: {exc.quote[:80]!r}")
                continue
            record["subject"], subj_resolved = normalize(record["subject"])
            record["object"], obj_resolved = normalize(record["object"])
            if not (subj_resolved and obj_resolved):
                notes.append(f"unresolved entity: subject={record['subject']!r} object={record['object']!r}")
            records.append(record)

        if not records and call.result.claims:
            # Every claim in this attempt failed span verification -- that's a
            # real attempt failure, not a partial batch, so retry the whole call.
            error_note = last_span_error
            continue

        avg_confidence = statistics.mean(r["extraction_confidence"] for r in records) if records else 1.0
        if avg_confidence < stage_cfg.escalation.confidence_threshold:
            consecutive_low_confidence += 1
        else:
            consecutive_low_confidence = 0

        if (
            consecutive_low_confidence >= stage_cfg.escalation.consecutive_failures_to_escalate
            and not escalated
            and tier_name != "strong"
            and stage_cfg.escalation.max_escalations > 0
        ):
            tier_name = "strong"
            escalated = True
            consecutive_low_confidence = 0
            notes.append(f"escalated to strong tier after low confidence ({avg_confidence:.2f})")
            continue

        return PaperExtractionOutcome(records, fetched.status, "done", attempt, total_cost, notes)

    notes.append(f"quarantined after {stage_cfg.max_retries} attempts, last error: {error_note}")
    return PaperExtractionOutcome([], fetched.status, "quarantined", stage_cfg.max_retries, total_cost, notes)
