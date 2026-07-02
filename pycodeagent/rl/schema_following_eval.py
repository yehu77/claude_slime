"""Evaluation helpers for schema-following predictors and local SFT runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, Field

from pycodeagent.rl.schema_following import (
    SchemaFollowingSample,
    render_exposed_tool_call_text,
)
from pycodeagent.rl.schema_following_dataset import read_schema_following_jsonl
from pycodeagent.rl.serializer import serialize_schema_following_sample
from pycodeagent.tools.families import (
    build_claude_canonical_registry,
    build_codex_canonical_registry,
)
from pycodeagent.tools.spec import ToolAdapter, ToolArgumentError, ToolProfile, ToolView


class SchemaFollowingPredictor(Protocol):
    """Protocol for models that predict a schema-following tool-call block."""

    def predict(
        self,
        sample: SchemaFollowingSample,
        prompt_text: str,
    ) -> str:
        """Return generated text for one evaluation sample."""
        ...


class SchemaFollowingEvaluationCase(BaseModel):
    """Detailed outcome for a single evaluation sample."""

    sample_id: str
    split: str
    task_id: str
    tool_profile_id: str
    mutation_category: str
    prompt_text: str
    expected_text: str
    predicted_text: str
    expected_exposed_tool: str
    predicted_exposed_tool: str | None = None
    expected_canonical_intent: dict[str, Any]
    predicted_canonical_intent: dict[str, Any] | None = None
    parse_ok: bool
    tool_name_ok: bool
    schema_valid: bool
    canonical_intent_ok: bool
    exact_match: bool
    stale_canonical_name: bool
    error_code: str | None = None
    error_message: str | None = None


class SchemaFollowingSplitMetrics(BaseModel):
    """Aggregated schema-following metrics for one split."""

    split: str
    sample_count: int
    parse_rate: float
    tool_name_accuracy: float
    schema_valid_rate: float
    canonical_intent_accuracy: float
    exact_match_rate: float
    stale_canonical_name_rate: float
    error_counts: dict[str, int] = Field(default_factory=dict)


class SchemaFollowingEvaluationReport(BaseModel):
    """Structured evaluation report across one or more splits."""

    model_label: str
    dataset_dir: str
    splits: list[str]
    metrics_by_split: dict[str, SchemaFollowingSplitMetrics]
    overall: SchemaFollowingSplitMetrics
    failed_cases: list[SchemaFollowingEvaluationCase] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SchemaFollowingComparisonDelta(BaseModel):
    """Metric deltas between two evaluation reports."""

    split: str
    parse_rate_delta: float
    tool_name_accuracy_delta: float
    schema_valid_rate_delta: float
    canonical_intent_accuracy_delta: float
    exact_match_rate_delta: float
    stale_canonical_name_rate_delta: float


class SchemaFollowingComparisonReport(BaseModel):
    """Before/after comparison for schema-following evaluation runs."""

    dataset_dir: str
    baseline_label: str
    trained_label: str
    baseline_report_path: str
    trained_report_path: str
    deltas_by_split: dict[str, SchemaFollowingComparisonDelta]
    overall_delta: SchemaFollowingComparisonDelta
    metadata: dict[str, Any] = Field(default_factory=dict)


class CanonicalIntentBaselinePredictor:
    """Baseline that ignores the exposed ToolView and emits canonical calls."""

    def predict(
        self,
        sample: SchemaFollowingSample,
        prompt_text: str,
    ) -> str:
        del prompt_text
        return render_exposed_tool_call_text(
            call_id=sample.target_tool_call.call_id,
            name=sample.canonical_intent.tool,
            arguments=sample.canonical_intent.arguments,
        )


def build_schema_following_prompt_text(sample: SchemaFollowingSample) -> str:
    """Return the serialized prompt text without the target tool-call block."""
    serialized = serialize_schema_following_sample(sample)
    return "".join(segment.text for segment in serialized.segments if not segment.trainable)


def parse_tool_call_block(text: str) -> dict[str, Any]:
    """Parse a generated <|tool|> ... <|end|> block into its JSON payload."""
    start_marker = "<|tool|>"
    end_marker = "<|end|>"
    start = text.find(start_marker)
    if start < 0:
        raise ValueError("missing_tool_call_block")

    start += len(start_marker)
    end = text.find(end_marker, start)
    if end < 0:
        raise ValueError("missing_end_marker")

    payload_text = text[start:end].strip()
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid_json: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("invalid_payload_type")
    if not isinstance(payload.get("name"), str) or not payload["name"].strip():
        raise ValueError("invalid_payload_name")
    has_arguments = isinstance(payload.get("arguments"), dict)
    has_input_text = isinstance(payload.get("input_text"), str)
    if not has_arguments and not has_input_text:
        raise ValueError("invalid_payload_arguments")
    return payload


def load_schema_following_profile_map(dataset_dir: str | Path) -> dict[str, ToolProfile]:
    """Load ToolProfiles reconstructed from profile_manifest.json."""
    dataset_dir = Path(dataset_dir)
    manifest_path = dataset_dir / "profile_manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Missing profile manifest: {manifest_path}")

    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    profiles: dict[str, ToolProfile] = {}
    for entry in payload.get("profiles", []):
        tools = [
            ToolView(
                canonical_name=tool["canonical_name"],
                exposed_name=tool["exposed_name"],
                description=tool["description"],
                input_schema=tool["input_schema"],
                contract_kind=tool.get("contract_kind", "function"),
                input_format=tool.get("input_format"),
                version=tool.get("version", "default"),
                metadata=dict(tool.get("metadata", {})),
            )
            for tool in entry["tools"]
        ]
        adapters = {
            tool["exposed_name"]: ToolAdapter.model_validate(tool.get("adapter", {}))
            for tool in entry["tools"]
        }
        profiles[entry["profile_id"]] = ToolProfile(
            profile_id=entry["profile_id"],
            tools=tools,
            adapters=adapters,
            metadata={
                "category": entry.get("category"),
                "mode": entry.get("mode"),
                "seed": entry.get("seed"),
                "split_role": entry.get("split_role"),
                "family": entry.get("family"),
                "native_profile_kind": entry.get("native_profile_kind"),
                "mutation_source_family": entry.get("mutation_source_family"),
            },
        )
    return profiles


def evaluate_schema_following_predictor(
    dataset_dir: str | Path,
    *,
    predictor: SchemaFollowingPredictor,
    model_label: str,
    splits: list[str],
    failed_case_limit: int | None = 100,
    metadata: dict[str, Any] | None = None,
) -> SchemaFollowingEvaluationReport:
    """Evaluate a predictor on one or more schema-following splits."""
    dataset_dir = Path(dataset_dir)
    profiles = load_schema_following_profile_map(dataset_dir)
    registries = {
        profile_id: _canonical_registry_for_profile(profile)
        for profile_id, profile in profiles.items()
    }

    metrics_by_split: dict[str, SchemaFollowingSplitMetrics] = {}
    failed_cases: list[SchemaFollowingEvaluationCase] = []
    all_cases: list[SchemaFollowingEvaluationCase] = []

    for split in splits:
        samples = read_schema_following_jsonl(dataset_dir / f"{split}.jsonl")
        split_cases: list[SchemaFollowingEvaluationCase] = []
        for sample in samples:
            prompt_text = build_schema_following_prompt_text(sample)
            predicted_text = predictor.predict(sample, prompt_text)
            case = _evaluate_sample(
                sample,
                prompt_text=prompt_text,
                predicted_text=predicted_text,
                profile=profiles[sample.tool_profile_id],
                registry=registries[sample.tool_profile_id],
            )
            split_cases.append(case)
            all_cases.append(case)
            if case.error_code is not None:
                if failed_case_limit is None or len(failed_cases) < failed_case_limit:
                    failed_cases.append(case)

        metrics_by_split[split] = _summarize_cases(split, split_cases)

    overall = _summarize_cases("overall", all_cases)
    return SchemaFollowingEvaluationReport(
        model_label=model_label,
        dataset_dir=str(dataset_dir),
        splits=splits,
        metrics_by_split=metrics_by_split,
        overall=overall,
        failed_cases=failed_cases,
        metadata=metadata or {},
    )


def _canonical_registry_for_profile(profile: ToolProfile):
    native_profile_kind = profile.metadata.get("native_profile_kind")
    family = profile.metadata.get("family")
    if native_profile_kind == "native_claude" or family == "claude":
        return build_claude_canonical_registry()
    if native_profile_kind == "native_codex" or family == "codex":
        return build_codex_canonical_registry()
    raise ValueError(
        "Schema-following evaluation requires native-family profile metadata; "
        f"got family={family!r}, native_profile_kind={native_profile_kind!r}"
    )


def write_schema_following_eval_report_json(
    path: str | Path,
    report: SchemaFollowingEvaluationReport,
) -> None:
    """Write a schema-following evaluation report to JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_schema_following_eval_report_markdown(
    path: str | Path,
    report: SchemaFollowingEvaluationReport,
) -> None:
    """Write a concise Markdown summary for one evaluation report."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# Schema-Following Eval: {report.model_label}",
        "",
        f"- Dataset: `{report.dataset_dir}`",
        f"- Splits: {', '.join(report.splits)}",
        "",
        "| Split | Count | Parse | Tool Name | Schema Valid | Canonical Intent | Exact Match | Stale Canonical |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split in report.splits + ["overall"]:
        metrics = report.overall if split == "overall" else report.metrics_by_split[split]
        lines.append(
            "| "
            f"{metrics.split} | {metrics.sample_count} | "
            f"{metrics.parse_rate:.3f} | {metrics.tool_name_accuracy:.3f} | "
            f"{metrics.schema_valid_rate:.3f} | {metrics.canonical_intent_accuracy:.3f} | "
            f"{metrics.exact_match_rate:.3f} | {metrics.stale_canonical_name_rate:.3f} |"
        )
    if report.failed_cases:
        lines.extend(
            [
                "",
                "## Failed Cases",
                "",
                "| Sample | Split | Error | Expected Tool | Predicted Tool |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for case in report.failed_cases[:20]:
            lines.append(
                "| "
                f"{case.sample_id} | {case.split} | {case.error_code or ''} | "
                f"{case.expected_exposed_tool} | {case.predicted_exposed_tool or ''} |"
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compare_schema_following_reports(
    baseline: SchemaFollowingEvaluationReport,
    trained: SchemaFollowingEvaluationReport,
    *,
    baseline_report_path: str,
    trained_report_path: str,
    metadata: dict[str, Any] | None = None,
) -> SchemaFollowingComparisonReport:
    """Build a before/after comparison report for schema-following evaluation."""
    split_names = sorted(set(baseline.metrics_by_split) | set(trained.metrics_by_split))
    deltas: dict[str, SchemaFollowingComparisonDelta] = {}
    for split in split_names:
        before = baseline.metrics_by_split[split]
        after = trained.metrics_by_split[split]
        deltas[split] = _metric_delta(split, before, after)

    return SchemaFollowingComparisonReport(
        dataset_dir=baseline.dataset_dir,
        baseline_label=baseline.model_label,
        trained_label=trained.model_label,
        baseline_report_path=baseline_report_path,
        trained_report_path=trained_report_path,
        deltas_by_split=deltas,
        overall_delta=_metric_delta("overall", baseline.overall, trained.overall),
        metadata=metadata or {},
    )


def write_schema_following_comparison_json(
    path: str | Path,
    comparison: SchemaFollowingComparisonReport,
) -> None:
    """Write a before/after comparison report to JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(comparison.model_dump(mode="json"), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def write_schema_following_comparison_markdown(
    path: str | Path,
    comparison: SchemaFollowingComparisonReport,
) -> None:
    """Write a concise Markdown before/after comparison."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Schema-Following Before/After",
        "",
        f"- Dataset: `{comparison.dataset_dir}`",
        f"- Baseline: `{comparison.baseline_label}`",
        f"- Trained: `{comparison.trained_label}`",
        "",
        "| Split | Parse Δ | Tool Name Δ | Schema Valid Δ | Canonical Intent Δ | Exact Match Δ | Stale Canonical Δ |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split_name, delta in comparison.deltas_by_split.items():
        lines.append(
            "| "
            f"{split_name} | {delta.parse_rate_delta:+.3f} | {delta.tool_name_accuracy_delta:+.3f} | "
            f"{delta.schema_valid_rate_delta:+.3f} | {delta.canonical_intent_accuracy_delta:+.3f} | "
            f"{delta.exact_match_rate_delta:+.3f} | {delta.stale_canonical_name_rate_delta:+.3f} |"
        )
    overall = comparison.overall_delta
    lines.extend(
        [
            "",
            "## Overall",
            "",
            f"- Parse rate delta: `{overall.parse_rate_delta:+.3f}`",
            f"- Tool-name accuracy delta: `{overall.tool_name_accuracy_delta:+.3f}`",
            f"- Schema-valid rate delta: `{overall.schema_valid_rate_delta:+.3f}`",
            f"- Canonical-intent accuracy delta: `{overall.canonical_intent_accuracy_delta:+.3f}`",
            f"- Exact-match delta: `{overall.exact_match_rate_delta:+.3f}`",
            f"- Stale-canonical-name delta: `{overall.stale_canonical_name_rate_delta:+.3f}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _evaluate_sample(
    sample: SchemaFollowingSample,
    *,
    prompt_text: str,
    predicted_text: str,
    profile: ToolProfile,
    registry: dict[str, Any],
) -> SchemaFollowingEvaluationCase:
    expected_name = sample.target_tool_call.name
    expected_canonical = sample.canonical_intent.model_dump(mode="json")
    expected_canonical_name = sample.canonical_intent.tool
    expected_freeform = (
        sample.target_tool_call.input_text is not None
        or sample.canonical_intent.input_text is not None
    )
    stale_canonical_name = False
    predicted_name: str | None = None
    predicted_canonical: dict[str, Any] | None = None

    if expected_freeform:
        return SchemaFollowingEvaluationCase(
            sample_id=sample.sample_id,
            split=sample.split,
            task_id=sample.task_id,
            tool_profile_id=sample.tool_profile_id,
            mutation_category=sample.mutation_category,
            prompt_text=prompt_text,
            expected_text=sample.target_text,
            predicted_text=predicted_text,
            expected_exposed_tool=expected_name,
            expected_canonical_intent=expected_canonical,
            parse_ok=False,
            tool_name_ok=False,
            schema_valid=False,
            canonical_intent_ok=False,
            exact_match=False,
            stale_canonical_name=False,
            error_code="freeform_not_supported_in_schema_following_eval",
            error_message=(
                "Schema-following evaluation currently expects object arguments; "
                "freeform tool-call payloads are not yet scored here."
            ),
        )

    try:
        payload = parse_tool_call_block(predicted_text)
    except ValueError as exc:
        error_code = _normalize_parse_error(str(exc))
        return SchemaFollowingEvaluationCase(
            sample_id=sample.sample_id,
            split=sample.split,
            task_id=sample.task_id,
            tool_profile_id=sample.tool_profile_id,
            mutation_category=sample.mutation_category,
            prompt_text=prompt_text,
            expected_text=sample.target_text,
            predicted_text=predicted_text,
            expected_exposed_tool=expected_name,
            expected_canonical_intent=expected_canonical,
            parse_ok=False,
            tool_name_ok=False,
            schema_valid=False,
            canonical_intent_ok=False,
            exact_match=False,
            stale_canonical_name=False,
            error_code=error_code,
            error_message=str(exc),
        )

    predicted_name = payload["name"]
    stale_canonical_name = (
        predicted_name == expected_canonical_name and predicted_name != expected_name
    )
    resolved = profile.get_tool(predicted_name)
    if resolved is None:
        return SchemaFollowingEvaluationCase(
            sample_id=sample.sample_id,
            split=sample.split,
            task_id=sample.task_id,
            tool_profile_id=sample.tool_profile_id,
            mutation_category=sample.mutation_category,
            prompt_text=prompt_text,
            expected_text=sample.target_text,
            predicted_text=predicted_text,
            expected_exposed_tool=expected_name,
            predicted_exposed_tool=predicted_name,
            expected_canonical_intent=expected_canonical,
            parse_ok=True,
            tool_name_ok=False,
            schema_valid=False,
            canonical_intent_ok=False,
            exact_match=False,
            stale_canonical_name=stale_canonical_name,
            error_code="unknown_tool_name",
            error_message=f"Unknown tool name for current profile: {predicted_name}",
        )

    view, _ = resolved
    canonical_tool = registry.get(view.canonical_name)
    predicted_arguments = payload.get("arguments")
    if not isinstance(predicted_arguments, dict):
        return SchemaFollowingEvaluationCase(
            sample_id=sample.sample_id,
            split=sample.split,
            task_id=sample.task_id,
            tool_profile_id=sample.tool_profile_id,
            mutation_category=sample.mutation_category,
            prompt_text=prompt_text,
            expected_text=sample.target_text,
            predicted_text=predicted_text,
            expected_exposed_tool=expected_name,
            predicted_exposed_tool=predicted_name,
            expected_canonical_intent=expected_canonical,
            parse_ok=True,
            tool_name_ok=(predicted_name == expected_name),
            schema_valid=False,
            canonical_intent_ok=False,
            exact_match=False,
            stale_canonical_name=stale_canonical_name,
            error_code="freeform_not_supported_in_schema_following_eval",
            error_message=(
                "Schema-following evaluation currently expects object arguments; "
                "freeform tool-call payloads are not yet scored here."
            ),
        )
    try:
        _, canonical_args = profile.map_call_arguments(
            predicted_name,
            predicted_arguments,
            canonical_tool=canonical_tool,
        )
    except ToolArgumentError as exc:
        return SchemaFollowingEvaluationCase(
            sample_id=sample.sample_id,
            split=sample.split,
            task_id=sample.task_id,
            tool_profile_id=sample.tool_profile_id,
            mutation_category=sample.mutation_category,
            prompt_text=prompt_text,
            expected_text=sample.target_text,
            predicted_text=predicted_text,
            expected_exposed_tool=expected_name,
            predicted_exposed_tool=predicted_name,
            expected_canonical_intent=expected_canonical,
            parse_ok=True,
            tool_name_ok=(predicted_name == expected_name),
            schema_valid=False,
            canonical_intent_ok=False,
            exact_match=False,
            stale_canonical_name=stale_canonical_name,
            error_code="schema_validation_error",
            error_message=str(exc),
        )

    predicted_canonical = {
        "tool": view.canonical_name,
        "arguments": canonical_args,
    }
    canonical_ok = predicted_canonical == expected_canonical
    exact_match = predicted_text == sample.target_text
    error_code = None
    error_message = None
    if not canonical_ok:
        error_code = "canonical_intent_mismatch"
        error_message = (
            f"{predicted_canonical!r} does not match expected {expected_canonical!r}"
        )
    elif not exact_match:
        error_code = "exact_text_mismatch"
        error_message = "Predicted tool call is semantically correct but text differs"

    return SchemaFollowingEvaluationCase(
        sample_id=sample.sample_id,
        split=sample.split,
        task_id=sample.task_id,
        tool_profile_id=sample.tool_profile_id,
        mutation_category=sample.mutation_category,
        prompt_text=prompt_text,
        expected_text=sample.target_text,
        predicted_text=predicted_text,
        expected_exposed_tool=expected_name,
        predicted_exposed_tool=predicted_name,
        expected_canonical_intent=expected_canonical,
        predicted_canonical_intent=predicted_canonical,
        parse_ok=True,
        tool_name_ok=(predicted_name == expected_name),
        schema_valid=True,
        canonical_intent_ok=canonical_ok,
        exact_match=exact_match,
        stale_canonical_name=stale_canonical_name,
        error_code=error_code,
        error_message=error_message,
    )


def _normalize_parse_error(error: str) -> str:
    if error == "missing_tool_call_block":
        return "missing_tool_call_block"
    if error == "missing_end_marker":
        return "missing_end_marker"
    if error.startswith("invalid_json:"):
        return "invalid_json"
    if error.startswith("invalid_payload"):
        return error
    return "parse_error"


def _summarize_cases(
    split: str,
    cases: list[SchemaFollowingEvaluationCase],
) -> SchemaFollowingSplitMetrics:
    total = len(cases)
    if total == 0:
        return SchemaFollowingSplitMetrics(
            split=split,
            sample_count=0,
            parse_rate=0.0,
            tool_name_accuracy=0.0,
            schema_valid_rate=0.0,
            canonical_intent_accuracy=0.0,
            exact_match_rate=0.0,
            stale_canonical_name_rate=0.0,
            error_counts={},
        )

    error_counts: dict[str, int] = {}
    for case in cases:
        if case.error_code is not None:
            error_counts[case.error_code] = error_counts.get(case.error_code, 0) + 1

    return SchemaFollowingSplitMetrics(
        split=split,
        sample_count=total,
        parse_rate=sum(1 for case in cases if case.parse_ok) / total,
        tool_name_accuracy=sum(1 for case in cases if case.tool_name_ok) / total,
        schema_valid_rate=sum(1 for case in cases if case.schema_valid) / total,
        canonical_intent_accuracy=(
            sum(1 for case in cases if case.canonical_intent_ok) / total
        ),
        exact_match_rate=sum(1 for case in cases if case.exact_match) / total,
        stale_canonical_name_rate=(
            sum(1 for case in cases if case.stale_canonical_name) / total
        ),
        error_counts=error_counts,
    )


def _metric_delta(
    split: str,
    baseline: SchemaFollowingSplitMetrics,
    trained: SchemaFollowingSplitMetrics,
) -> SchemaFollowingComparisonDelta:
    return SchemaFollowingComparisonDelta(
        split=split,
        parse_rate_delta=trained.parse_rate - baseline.parse_rate,
        tool_name_accuracy_delta=(
            trained.tool_name_accuracy - baseline.tool_name_accuracy
        ),
        schema_valid_rate_delta=trained.schema_valid_rate - baseline.schema_valid_rate,
        canonical_intent_accuracy_delta=(
            trained.canonical_intent_accuracy - baseline.canonical_intent_accuracy
        ),
        exact_match_rate_delta=trained.exact_match_rate - baseline.exact_match_rate,
        stale_canonical_name_rate_delta=(
            trained.stale_canonical_name_rate - baseline.stale_canonical_name_rate
        ),
    )
