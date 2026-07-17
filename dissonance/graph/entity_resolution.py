from __future__ import annotations

# v1 = static normalization table. Log unresolved terms rather than chasing
# perfect entity resolution -- plan.md §9 flags this as a rabbit hole risk.
_CANONICAL: dict[str, str] = {
    "gsm8k": "GSM8K",
    "mmlu": "MMLU",
    "mmlu-pro": "MMLU-Pro",
    "hellaswag": "HellaSwag",
    "truthfulqa": "TruthfulQA",
    "humaneval": "HumanEval",
    "mbpp": "MBPP",
    "big-bench hard": "BIG-Bench Hard",
    "bbh": "BIG-Bench Hard",
    "arc": "ARC",
    "arc-challenge": "ARC-Challenge",
    "gpqa": "GPQA",
    "math": "MATH",
    "few-shot prompting": "few-shot prompting",
    "zero-shot prompting": "zero-shot prompting",
    "chain-of-thought": "chain-of-thought prompting",
    "chain-of-thought prompting": "chain-of-thought prompting",
    "cot": "chain-of-thought prompting",
    "cot prompting": "chain-of-thought prompting",
    "rag": "retrieval-augmented generation",
    "retrieval-augmented generation": "retrieval-augmented generation",
    "llm-as-a-judge": "LLM-as-a-judge",
    "llm as a judge": "LLM-as-a-judge",
}


def normalize(term: str | None) -> tuple[str | None, bool]:
    """Returns (normalized_term, was_resolved)."""
    if not term:
        return term, True
    key = " ".join(term.strip().lower().split())
    if key in _CANONICAL:
        return _CANONICAL[key], True
    return term.strip(), False
