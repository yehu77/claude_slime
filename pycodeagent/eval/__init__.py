"""Batch evaluation and experiment module.

Provides:
- BatchRunner: Execute multiple task/profile combinations
- run_batch: Convenience function
- compute_metrics: Aggregate metrics from run summaries
- write_batch_reports: Write structured reports
- ExperimentConfig: Structured experiment configuration
- ExperimentRunner: Orchestrate task/profile/seed experiments
- run_experiment: Convenience function
- load_experiment_analysis: Load experiment outputs for analysis
- build_profile_comparison_table: Build profile comparison tables
- build_seed_comparison_table: Build seed comparison tables
- StudyConfig: Study configuration for mutation sensitivity
- MutationStudyRunner: Run mutation sensitivity studies
- StudyReport: Write study reports
- run_study_from_config: Run study from config file path
- run_study: Run study from StudyConfig object
"""

from pycodeagent.eval.analysis import (
    ExperimentAnalysis,
    RunRecord,
    compute_grouped_metrics,
    get_run_field,
    load_experiment_analysis,
    load_experiment_runs,
    load_runs_from_jsonl as load_analysis_runs_jsonl,
)
from pycodeagent.eval.batch_runner import (
    BatchResult,
    BatchRunner,
    RunSummary,
    run_batch,
)
from pycodeagent.eval.experiment_config import ExperimentConfig
from pycodeagent.eval.experiment_runner import (
    ExperimentManifest,
    ExperimentResult,
    ExperimentRunner,
    run_experiment,
)
from pycodeagent.eval.metrics import compute_metrics
from pycodeagent.eval.report import (
    load_failed_cases_jsonl,
    load_runs_jsonl,
    load_summary_json,
    write_batch_reports,
)
from pycodeagent.eval.runtime_behavior_audit import (
    RunBehaviorSummary,
    RuntimeBehaviorAudit,
    build_runtime_behavior_audit,
)
from pycodeagent.eval.real_provider_behavior_baseline import (
    BehaviorBaselineResult,
    BehaviorBaselineSummary,
    FailureBucketsReport,
    PromotionGateResult,
    build_behavior_baseline_summary,
    build_failure_buckets_report,
    load_realistic_runtime_tasks,
    run_behavior_baseline,
    run_real_provider_behavior_baseline,
)
from pycodeagent.eval.real_provider_credibility_bundle import (
    CredibilityGateResult,
    RealProviderCredibilityBundleResult,
    build_real_provider_credibility_bundle_from_runs,
    run_provider_credibility_bundle,
    run_real_provider_credibility_bundle,
)
from pycodeagent.eval.toolview_mutation_data_generation import (
    ToolViewMutationDataGenerationResult,
    build_toolview_mutation_data_generation_from_runs,
    run_real_provider_toolview_mutation_data_generation,
    run_toolview_mutation_data_generation,
)
from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.eval.study_runner import (
    ModeComparison,
    MutationStudyRunner,
    SeedComparison,
    SeedVariability,
    StudyResult,
)
from pycodeagent.eval.study_report import StudyReport, write_study_report
from pycodeagent.eval.run_study import (
    run_study,
    run_study_from_config,
    run_study_from_provider_config,
    run_study_with_provider_config,
)
from pycodeagent.eval.runtime_observed_postrun import (
    RuntimeObservedStudyBundleResult,
    prepare_study_runtime_observed_bundle,
)
from pycodeagent.eval.native_family_acceptance import (
    NativeFamilyAcceptanceReport,
    run_native_family_acceptance,
)
from pycodeagent.eval.tables import (
    build_category_profile_table,
    build_error_breakdown_table,
    build_profile_comparison_table,
    build_seed_comparison_table,
    table_to_csv,
    table_to_markdown,
)

__all__ = [
    # Batch runner
    "BatchRunner",
    "BatchResult",
    "RunSummary",
    "run_batch",
    # Experiment
    "ExperimentConfig",
    "ExperimentRunner",
    "ExperimentResult",
    "ExperimentManifest",
    "run_experiment",
    # Analysis
    "ExperimentAnalysis",
    "RunRecord",
    "compute_grouped_metrics",
    "get_run_field",
    "load_experiment_analysis",
    "load_experiment_runs",
    "load_analysis_runs_jsonl",
    # Tables
    "build_profile_comparison_table",
    "build_seed_comparison_table",
    "build_category_profile_table",
    "build_error_breakdown_table",
    "table_to_markdown",
    "table_to_csv",
    # Metrics
    "compute_metrics",
    # Report
    "write_batch_reports",
    "load_summary_json",
    "load_runs_jsonl",
    "load_failed_cases_jsonl",
    "build_runtime_behavior_audit",
    "RuntimeBehaviorAudit",
    "RunBehaviorSummary",
    "run_real_provider_behavior_baseline",
    "run_behavior_baseline",
    "load_realistic_runtime_tasks",
    "build_behavior_baseline_summary",
    "build_failure_buckets_report",
    "BehaviorBaselineResult",
    "BehaviorBaselineSummary",
    "FailureBucketsReport",
    "PromotionGateResult",
    "run_real_provider_credibility_bundle",
    "run_provider_credibility_bundle",
    "build_real_provider_credibility_bundle_from_runs",
    "RealProviderCredibilityBundleResult",
    "CredibilityGateResult",
    "run_real_provider_toolview_mutation_data_generation",
    "run_toolview_mutation_data_generation",
    "build_toolview_mutation_data_generation_from_runs",
    "ToolViewMutationDataGenerationResult",
    # Study
    "StudyConfig",
    "MutationStudyRunner",
    "StudyResult",
    "ModeComparison",
    "SeedComparison",
    "SeedVariability",
    "StudyReport",
    "write_study_report",
    "RuntimeObservedStudyBundleResult",
    "prepare_study_runtime_observed_bundle",
    "NativeFamilyAcceptanceReport",
    "run_native_family_acceptance",
    # Run study
    "run_study_from_config",
    "run_study",
    "run_study_from_provider_config",
    "run_study_with_provider_config",
]
