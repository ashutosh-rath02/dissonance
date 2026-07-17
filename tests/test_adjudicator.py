from unittest.mock import MagicMock

import pytest

from dissonance.adjudicator.client import AdjudicationCall, AdjudicatorClient
from dissonance.adjudicator.context import context_window
from dissonance.adjudicator.pipeline import adjudicate_pair
from dissonance.adjudicator.schema import AdjudicatorVerdict
from dissonance.supervisor.config import RunConfig


def _claim(paper_id="arxiv:2501.00001"):
    return {
        "paper_id": paper_id,
        "assertion": "Few-shot prompting improves accuracy on GSM8K",
        "subject": "few-shot prompting",
        "object": "GSM8K accuracy",
        "direction": "increases",
        "effect_size": {"value": 12.3, "unit": "pp", "reported": True},
        "conditions": {"model_class": "7B open-weight"},
    }


def _verdict(**overrides):
    defaults = {
        "type": "direct",
        "verdict": "genuine",
        "extraction_error_claim": None,
        "rationale": "they disagree",
        "confidence": 0.9,
    }
    defaults.update(overrides)
    return AdjudicatorVerdict(**defaults)


@pytest.fixture
def run_config():
    return RunConfig.load("configs/run.yaml")


class TestContextWindow:
    def test_extracts_window_around_span(self):
        text = "a" * 1000 + "TARGET" + "b" * 1000
        span = {"char_start": 1000, "char_end": 1006}

        window = context_window(text, span, window=50)

        assert "TARGET" in window
        assert len(window) == 50 + 6 + 50

    def test_clamps_at_text_boundaries(self):
        text = "short text with a span"
        span = {"char_start": 0, "char_end": 5}

        window = context_window(text, span, window=500)

        assert window == text


class TestAdjudicatePair:
    def _client(self, calls: list[AdjudicationCall]):
        client = MagicMock(spec=AdjudicatorClient)
        client.adjudicate.side_effect = calls
        return client

    def test_high_confidence_first_tier_does_not_escalate(self, run_config):
        client = self._client([AdjudicationCall(result=_verdict(confidence=0.9), cost_usd=0.001, model="gpt-4.1-mini")])

        outcome = adjudicate_pair(_claim(), "context a", _claim(), "context b", run_config, client)

        assert outcome.verdict == "genuine"
        assert outcome.loops_used == 1
        assert client.adjudicate.call_count == 1

    def test_low_confidence_escalates_to_strong_tier(self, run_config):
        calls = [
            AdjudicationCall(result=_verdict(confidence=0.3), cost_usd=0.001, model="gpt-4.1-mini"),
            AdjudicationCall(result=_verdict(confidence=0.9, rationale="strong tier says genuine"), cost_usd=0.005, model="gpt-4.1"),
        ]
        client = self._client(calls)

        outcome = adjudicate_pair(_claim(), "context a", _claim(), "context b", run_config, client)

        assert outcome.loops_used == 2
        assert outcome.rationale == "strong tier says genuine"
        assert client.adjudicate.call_count == 2

    def test_exhausting_tiers_at_low_confidence_becomes_insufficient_context(self, run_config):
        calls = [
            AdjudicationCall(result=_verdict(confidence=0.2), cost_usd=0.001, model="gpt-4.1-mini"),
            AdjudicationCall(result=_verdict(confidence=0.3), cost_usd=0.005, model="gpt-4.1"),
        ]
        client = self._client(calls)

        outcome = adjudicate_pair(_claim(), "context a", _claim(), "context b", run_config, client)

        assert outcome.verdict == "insufficient_context"
        assert outcome.loops_used == 2

    def test_model_reported_insufficient_context_does_not_escalate(self, run_config):
        client = self._client([
            AdjudicationCall(result=_verdict(verdict="insufficient_context", confidence=0.2), cost_usd=0.001, model="gpt-4.1-mini")
        ])

        outcome = adjudicate_pair(_claim(), "context a", _claim(), "context b", run_config, client)

        assert outcome.verdict == "insufficient_context"
        assert outcome.loops_used == 1
        assert client.adjudicate.call_count == 1

    def test_self_contradictory_genuine_verdict_escalates(self, run_config):
        calls = [
            AdjudicationCall(
                result=_verdict(confidence=0.95, rationale="These are compatible perspectives rather than contradictory."),
                cost_usd=0.001, model="gpt-4.1-mini",
            ),
            AdjudicationCall(
                result=_verdict(confidence=0.9, verdict="scope_difference", rationale="Genuinely a scope difference."),
                cost_usd=0.005, model="gpt-4.1",
            ),
        ]
        client = self._client(calls)

        outcome = adjudicate_pair(_claim(), "context a", _claim(), "context b", run_config, client)

        assert outcome.verdict == "scope_difference"
        assert outcome.loops_used == 2
        assert client.adjudicate.call_count == 2
        assert any("contradicted by its own rationale" in n for n in outcome.notes)

    def test_self_contradictory_genuine_at_last_tier_becomes_insufficient_context(self, run_config):
        calls = [
            AdjudicationCall(
                result=_verdict(confidence=0.95, rationale="There is no direct contradiction here."),
                cost_usd=0.001, model="gpt-4.1-mini",
            ),
            AdjudicationCall(
                result=_verdict(confidence=0.95, rationale="Still, there is no direct contradiction here."),
                cost_usd=0.005, model="gpt-4.1",
            ),
        ]
        client = self._client(calls)

        outcome = adjudicate_pair(_claim(), "context a", _claim(), "context b", run_config, client)

        assert outcome.verdict == "insufficient_context"
        assert outcome.loops_used == 2

    def test_extraction_error_carries_through_which_claim(self, run_config):
        client = self._client([
            AdjudicationCall(
                result=_verdict(verdict="extraction_error", extraction_error_claim="B", confidence=0.95),
                cost_usd=0.001, model="gpt-4.1-mini",
            )
        ])

        outcome = adjudicate_pair(_claim(), "context a", _claim(), "context b", run_config, client)

        assert outcome.verdict == "extraction_error"
        assert outcome.extraction_error_claim == "B"
