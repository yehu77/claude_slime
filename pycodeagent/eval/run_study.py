"""Minimal study launch entrypoint.

Provides a simple programmatic API to run mutation sensitivity studies:
    result = run_study_from_config(config_path, client_factory=...)

Reuses existing StudyConfig, MutationStudyRunner, and StudyReport infrastructure.
The client_factory is injectable for testing with fake clients.

Example:
    from pycodeagent.eval.run_study import run_study_from_config
    from pycodeagent.agent.llm_client import FakeLLMClient

    result = run_study_from_config(
        "configs/studies/first_mutation_sensitivity.json",
        client_factory=lambda: FakeLLMClient(responses=[...]),
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from pycodeagent.eval.study_config import StudyConfig
from pycodeagent.eval.study_runner import MutationStudyRunner, StudyResult
from pycodeagent.eval.study_report import StudyReport


def run_study_from_config(
    config_path: str | Path,
    client_factory: Callable[[], Any],
    *,
    output_dir: str | Path | None = None,
) -> StudyResult:
    """Run a mutation sensitivity study from a config file.

    This is the main entrypoint for running studies. It:
    1. Loads the study config from the given path
    2. Runs the study using MutationStudyRunner
    3. Writes the study report (study_config.json, study_summary.json, etc.)
    4. Returns the StudyResult

    Args:
        config_path: Path to the study config JSON file.
        client_factory: Factory function that creates a fresh LLM client.
                       For tests, use FakeLLMClient with preset responses.
        output_dir: Optional exact output directory for the study. If provided,
                   outputs will be written exactly to this directory (not nested
                   under study_id). If not provided, uses config's get_output_dir().

    Returns:
        StudyResult with experiment results, comparisons, and output paths.

    Example:
        # With a real client (for production)
        from pycodeagent.agent.openai_client import OpenAIClient

        result = run_study_from_config(
            "configs/studies/first_mutation_sensitivity.json",
            client_factory=lambda: OpenAIClient(model="gpt-4"),
        )

        # With a fake client (for testing)
        from pycodeagent.agent.llm_client import FakeLLMClient

        result = run_study_from_config(
            "configs/studies/first_mutation_sensitivity.json",
            client_factory=lambda: FakeLLMClient(responses=[
                '<|tool|>\\n{"id":"c1","name":"finish","arguments":{"answer":"Done"}}\\n<|end|>'
            ]),
        )
    """
    # Load config
    config = StudyConfig.load(config_path)

    # Run study with optional output dir override (does NOT mutate study_id)
    runner = MutationStudyRunner(client_factory)
    result = runner.run(config, output_dir_override=output_dir)

    # Write study report
    report = StudyReport(result.output_dir)
    report.write_all(result)

    return result


def run_study(
    config: StudyConfig,
    client_factory: Callable[[], Any],
    *,
    output_dir: str | Path | None = None,
) -> StudyResult:
    """Run a mutation sensitivity study from a StudyConfig object.

    Similar to run_study_from_config, but takes an already-loaded config.

    Args:
        config: Study configuration.
        client_factory: Factory function that creates a fresh LLM client.
        output_dir: Optional exact output directory for the study. If provided,
                   outputs will be written exactly to this directory. The
                   study_id is NOT modified.

    Returns:
        StudyResult with experiment results, comparisons, and output paths.
    """
    # Run study with optional output dir override (does NOT mutate study_id)
    runner = MutationStudyRunner(client_factory)
    result = runner.run(config, output_dir_override=output_dir)

    # Write study report
    report = StudyReport(result.output_dir)
    report.write_all(result)

    return result
