from unittest.mock import MagicMock

from evals.judge_schema import JudgeVerdict
from evals.llm_judge import JudgeCall, JudgeClient, judge_one
from dissonance.supervisor.config import RunConfig


def _claim():
    return {
        "claim_id": "c1",
        "paper_id": "arxiv:2501.01234",
        "assertion": "Few-shot prompting improves accuracy on GSM8K",
        "subject": "few-shot prompting",
        "object": "GSM8K accuracy",
        "direction": "increases",
        "effect_size": {"value": 12.3, "unit": "pp", "reported": True},
        "conditions": {"model_class": "7B open-weight"},
        "method_type": "benchmark_eval",
        "evidence_strength": "primary_result",
    }


def test_no_quote_returns_uncertain_with_zero_cost():
    judge = MagicMock(spec=JudgeClient)

    verdict, cost = judge_one(_claim(), None, judge, tier=MagicMock())

    assert verdict.verdict == "uncertain"
    assert cost == 0.0
    judge.judge.assert_not_called()


def test_quote_present_calls_judge_and_returns_its_verdict():
    tier = RunConfig.load("configs/run.yaml").models["strong"]
    judge = MagicMock(spec=JudgeClient)
    judge.judge.return_value = JudgeCall(
        result=JudgeVerdict(verdict="correct", rationale="matches"), cost_usd=0.002, model=tier.name
    )

    verdict, cost = judge_one(_claim(), "Few-shot prompting improves accuracy by 12.3 points", judge, tier)

    assert verdict.verdict == "correct"
    assert cost == 0.002
    judge.judge.assert_called_once()
