from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dissonance.extraction.extractor import Extractor, ExtractionCall
from dissonance.extraction.pipeline import extract_paper
from dissonance.extraction.schema import Conditions, EffectSize, ExtractedClaim, ExtractionResult
from dissonance.extraction.validator import SpanNotFoundError, build_claim_record
from dissonance.supervisor.config import RunConfig
from dissonance.supervisor.exceptions import IdenticalFailureBreakerTripped

SOURCE_TEXT = (
    "We evaluate few-shot prompting on GSM8K. Few-shot prompting improves accuracy "
    "by 12.3 points on grade-school math problems with 7B open-weight models."
)


def make_claim(quote: str = "Few-shot prompting improves accuracy by 12.3 points", confidence: float = 0.9):
    return ExtractedClaim(
        assertion="Few-shot prompting improves accuracy on GSM8K",
        subject="few-shot prompting",
        object="GSM8K accuracy",
        direction="increases",
        effect_size=EffectSize(value=12.3, unit="pp", reported=True),
        conditions=Conditions(model_class="7B open-weight", population_or_setting="grade-school math"),
        method_type="benchmark_eval",
        evidence_strength="primary_result",
        section="results",
        quote=quote,
        confidence=confidence,
    )


@pytest.fixture
def run_config():
    return RunConfig.load("configs/run.yaml")


class TestBuildClaimRecord:
    def test_valid_quote_produces_correct_span(self):
        claim = make_claim()
        record = build_claim_record(
            paper_id="arxiv:2501.01234", claim=claim, source_text=SOURCE_TEXT,
            model="gpt-5-mini", prompt_version="extraction_v1", run_id="run1",
        )
        start = record["source_span"]["char_start"]
        end = record["source_span"]["char_end"]
        assert SOURCE_TEXT[start:end] == claim.quote
        assert record["subject"] == "few-shot prompting"
        assert record["extraction_confidence"] == 0.9

    def test_quote_not_in_source_raises(self):
        claim = make_claim(quote="this text does not appear anywhere")
        with pytest.raises(SpanNotFoundError):
            build_claim_record(
                paper_id="arxiv:2501.01234", claim=claim, source_text=SOURCE_TEXT,
                model="gpt-5-mini", prompt_version="extraction_v1", run_id="run1",
            )


class TestExtractPaperPipeline:
    def _paper(self):
        return {"paper_id": "arxiv:2501.01234", "title": "Test Paper", "abstract": SOURCE_TEXT, "html_url": "https://arxiv.org/html/2501.01234"}

    def _mock_extractor(self, results: list[ExtractionCall]):
        extractor = MagicMock(spec=Extractor)
        extractor.extract.side_effect = results
        return extractor

    def test_successful_extraction_on_first_attempt(self, run_config, monkeypatch):
        monkeypatch.setattr(
            "dissonance.extraction.pipeline.fetch_full_text",
            lambda *a, **k: SimpleNamespace(text=SOURCE_TEXT, status="html_available"),
        )
        call = ExtractionCall(result=ExtractionResult(claims=[make_claim()]), cost_usd=0.001, model="gpt-5-mini")
        extractor = self._mock_extractor([call])

        outcome = extract_paper(self._paper(), run_config, extractor, run_id="run1")

        assert outcome.extraction_status == "done"
        assert outcome.attempts == 1
        assert len(outcome.claim_records) == 1
        assert extractor.extract.call_count == 1

    def test_span_failure_retries_then_succeeds(self, run_config, monkeypatch):
        monkeypatch.setattr(
            "dissonance.extraction.pipeline.fetch_full_text",
            lambda *a, **k: SimpleNamespace(text=SOURCE_TEXT, status="html_available"),
        )
        bad_call = ExtractionCall(
            result=ExtractionResult(claims=[make_claim(quote="not in the source text")]),
            cost_usd=0.001, model="gpt-5-mini",
        )
        good_call = ExtractionCall(result=ExtractionResult(claims=[make_claim()]), cost_usd=0.001, model="gpt-5-mini")
        extractor = self._mock_extractor([bad_call, good_call])

        outcome = extract_paper(self._paper(), run_config, extractor, run_id="run1")

        assert outcome.extraction_status == "done"
        assert outcome.attempts == 2
        assert extractor.extract.call_count == 2
        # the retry must have received the previous failure as feedback
        _, kwargs = extractor.extract.call_args_list[1]
        assert "not in the source text" in kwargs.get("error_note", "") or "not in the source text" in str(
            extractor.extract.call_args_list[1]
        )

    def test_partial_batch_keeps_valid_claims_and_drops_bad_one(self, run_config, monkeypatch):
        monkeypatch.setattr(
            "dissonance.extraction.pipeline.fetch_full_text",
            lambda *a, **k: SimpleNamespace(text=SOURCE_TEXT, status="html_available"),
        )
        mixed_call = ExtractionCall(
            result=ExtractionResult(claims=[make_claim(), make_claim(quote="this never appears")]),
            cost_usd=0.001, model="gpt-5-mini",
        )
        extractor = self._mock_extractor([mixed_call])

        outcome = extract_paper(self._paper(), run_config, extractor, run_id="run1")

        assert outcome.extraction_status == "done"
        assert outcome.attempts == 1
        assert len(outcome.claim_records) == 1
        assert extractor.extract.call_count == 1
        assert any("dropped claim" in n for n in outcome.notes)

    def test_exhausting_retries_quarantines_paper(self, run_config, monkeypatch):
        monkeypatch.setattr(
            "dissonance.extraction.pipeline.fetch_full_text",
            lambda *a, **k: SimpleNamespace(text=SOURCE_TEXT, status="html_available"),
        )
        # different failure signatures each time so the identical-failure breaker doesn't trip first
        calls = [
            ExtractionCall(result=ExtractionResult(claims=[make_claim(quote=f"never appears {i}")]), cost_usd=0.001, model="gpt-5-mini")
            for i in range(run_config.stages["extraction"].max_retries)
        ]
        extractor = self._mock_extractor(calls)

        outcome = extract_paper(self._paper(), run_config, extractor, run_id="run1")

        assert outcome.extraction_status == "quarantined"
        assert outcome.claim_records == []

    def test_identical_failure_breaker_trips(self, run_config, monkeypatch):
        monkeypatch.setattr(
            "dissonance.extraction.pipeline.fetch_full_text",
            lambda *a, **k: SimpleNamespace(text=SOURCE_TEXT, status="html_available"),
        )
        run_config.stages["extraction"].max_retries = 10  # breaker should trip well before this
        same_bad_call = ExtractionCall(
            result=ExtractionResult(claims=[make_claim(quote="never appears anywhere")]),
            cost_usd=0.001, model="gpt-5-mini",
        )
        extractor = self._mock_extractor([same_bad_call] * 10)

        with pytest.raises(IdenticalFailureBreakerTripped):
            extract_paper(self._paper(), run_config, extractor, run_id="run1")

    def test_no_text_available_quarantines_immediately(self, run_config, monkeypatch):
        monkeypatch.setattr(
            "dissonance.extraction.pipeline.fetch_full_text",
            lambda *a, **k: SimpleNamespace(text=None, status="unknown"),
        )
        extractor = self._mock_extractor([])

        outcome = extract_paper(self._paper(), run_config, extractor, run_id="run1")

        assert outcome.extraction_status == "quarantined"
        assert outcome.attempts == 0
        extractor.extract.assert_not_called()

    def test_fetch_network_error_leaves_paper_pending_not_quarantined(self, run_config, monkeypatch):
        def raise_dns_error(*a, **k):
            raise OSError("[Errno 11001] getaddrinfo failed")

        monkeypatch.setattr("dissonance.extraction.pipeline.fetch_full_text", raise_dns_error)
        extractor = self._mock_extractor([])

        outcome = extract_paper(self._paper(), run_config, extractor, run_id="run1")

        assert outcome.extraction_status == "pending"
        assert outcome.claim_records == []
        extractor.extract.assert_not_called()
