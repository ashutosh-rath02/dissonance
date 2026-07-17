import hashlib
import json

from evals.report import aggregate_extraction_runs, compute_faithfulness, compute_precision


class TestComputePrecision:
    def test_empty_log_is_not_a_number(self):
        result = compute_precision([])
        assert result["precision"] is None
        assert result["correct"] == 0

    def test_precision_excludes_uncertain_from_denominator(self):
        log = [
            {"verdict": "correct"},
            {"verdict": "correct"},
            {"verdict": "incorrect"},
            {"verdict": "uncertain"},
        ]
        result = compute_precision(log)
        assert result["correct"] == 2
        assert result["incorrect"] == 1
        assert result["uncertain"] == 1
        assert result["precision"] == 2 / 3

    def test_all_correct_is_perfect_precision(self):
        log = [{"verdict": "correct"}] * 5
        assert compute_precision(log)["precision"] == 1.0


class TestComputeFaithfulness:
    def _claim(self, paper_id: str, start: int, end: int, expected_hash: str) -> dict:
        return {
            "paper_id": paper_id,
            "source_span": {"char_start": start, "char_end": end, "verbatim_hash": expected_hash},
        }

    def test_matching_hash_counts_as_faithful(self):
        text = "The quick brown fox jumps over the lazy dog"
        quote = text[4:9]  # "quick"
        h = hashlib.sha256(quote.encode("utf-8")).hexdigest()
        claim = self._claim("p1", 4, 9, h)

        result = compute_faithfulness([claim], {"p1": text})

        assert result["checked"] == 1
        assert result["faithful"] == 1
        assert result["faithfulness_rate"] == 1.0

    def test_stale_hash_is_unfaithful(self):
        text = "The quick brown fox jumps over the lazy dog"
        claim = self._claim("p1", 4, 9, "not-the-real-hash")

        result = compute_faithfulness([claim], {"p1": text})

        assert result["checked"] == 1
        assert result["faithful"] == 0
        assert result["faithfulness_rate"] == 0.0

    def test_missing_source_text_is_not_faithful_or_unfaithful(self):
        claim = self._claim("p1", 0, 5, "irrelevant")

        result = compute_faithfulness([claim], {"p1": None})

        assert result["no_text"] == 1
        assert result["checked"] == 0
        assert result["faithfulness_rate"] is None

    def test_no_claims_reports_none_not_zero(self):
        result = compute_faithfulness([], {})
        assert result["faithfulness_rate"] is None
        assert result["total_claims"] == 0


class TestAggregateExtractionRuns:
    def test_ignores_non_extraction_manifests(self, tmp_path):
        run_dir = tmp_path / "abc123"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text(
            json.dumps({"pipeline": "ingest", "cost_usd": 5.0, "papers_touched": 10}),
            encoding="utf-8",
        )
        result = aggregate_extraction_runs(tmp_path)
        assert result["runs_seen"] == 0
        assert result["total_cost_usd"] == 0.0

    def test_aggregates_cost_and_loops_across_runs(self, tmp_path):
        for i, (cost, papers, loops) in enumerate([(0.04, 5, {"1": 4, "2": 1}), (0.02, 2, {"1": 2})]):
            run_dir = tmp_path / f"run{i}"
            run_dir.mkdir()
            (run_dir / "manifest.json").write_text(
                json.dumps({
                    "pipeline": "extraction", "cost_usd": cost,
                    "papers_touched": papers, "loops_to_resolution": loops,
                }),
                encoding="utf-8",
            )

        result = aggregate_extraction_runs(tmp_path)

        assert result["runs_seen"] == 2
        assert result["total_papers"] == 7
        assert result["total_cost_usd"] == 0.06000000000000001 or abs(result["total_cost_usd"] - 0.06) < 1e-9
        assert result["loops_histogram"] == {"1": 6, "2": 1}
        # (1*6 + 2*1) / 7
        assert abs(result["mean_loops"] - (8 / 7)) < 1e-9

    def test_no_manifests_is_not_a_number(self, tmp_path):
        result = aggregate_extraction_runs(tmp_path)
        assert result["runs_seen"] == 0
        assert result["cost_per_paper"] is None
        assert result["mean_loops"] is None
