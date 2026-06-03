"""Tests for schema-following evaluation reports and metrics."""

from __future__ import annotations

from pathlib import Path

from pycodeagent.rl.schema_following_eval import (
    CanonicalIntentBaselinePredictor,
    build_schema_following_prompt_text,
    evaluate_schema_following_predictor,
)
from pycodeagent.rl.schema_following_generate import (
    generate_synthetic_schema_following_data,
)
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.testing import cleanup_test_path, make_unique_test_dir


_TEST_NAMESPACE = "schema_following_eval"


def _get_test_dir() -> Path:
    return make_unique_test_dir(_TEST_NAMESPACE)


def _cleanup(path: Path) -> None:
    cleanup_test_path(path)


class _EchoPredictor:
    def predict(self, sample, prompt_text: str) -> str:
        assert prompt_text == build_schema_following_prompt_text(sample)
        return sample.target_text


class TestSchemaFollowingEval:
    def test_exact_predictor_scores_perfectly(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "dataset"
            result = generate_synthetic_schema_following_data(dataset_dir, num_intents=24, seed=7)
            split = result.present_splits[0]

            report = evaluate_schema_following_predictor(
                dataset_dir,
                predictor=_EchoPredictor(),
                model_label="echo",
                splits=[split],
            )

            metrics = report.metrics_by_split[split]
            assert metrics.sample_count > 0
            assert metrics.parse_rate == 1.0
            assert metrics.tool_name_accuracy == 1.0
            assert metrics.schema_valid_rate == 1.0
            assert metrics.canonical_intent_accuracy == 1.0
            assert metrics.exact_match_rate == 1.0
            assert report.failed_cases == []
        finally:
            _cleanup(tmp)

    def test_canonical_baseline_surfaces_stale_tool_names_on_mutated_schema(self) -> None:
        tmp = _get_test_dir()
        try:
            dataset_dir = tmp / "dataset"
            generate_synthetic_schema_following_data(dataset_dir, num_intents=24, seed=9)

            target_split = None
            for split_name in ("eval_unseen_name", "eval_unseen_schema", "eval_nested"):
                path = dataset_dir / f"{split_name}.jsonl"
                if path.exists() and read_schema_following_jsonl(path):
                    target_split = split_name
                    break
            assert target_split is not None

            report = evaluate_schema_following_predictor(
                dataset_dir,
                predictor=CanonicalIntentBaselinePredictor(),
                model_label="canonical_baseline",
                splits=[target_split],
            )

            metrics = report.metrics_by_split[target_split]
            assert metrics.sample_count > 0
            assert metrics.parse_rate == 1.0
            assert metrics.stale_canonical_name_rate > 0.0
            assert metrics.schema_valid_rate < 1.0
            assert any(
                case.error_code == "unknown_tool_name" for case in report.failed_cases
            )
        finally:
            _cleanup(tmp)
