"""Application orchestration for stable multi-source experiment loading."""

from collections import defaultdict
from pathlib import Path

from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.ports import ExperimentSourceReader
from metricproof.domain.models import (
    ExperimentCatalog,
    ExperimentRun,
    InputDiagnostic,
    MetricObservation,
    ScalarValue,
    Severity,
    diagnostic_sort_key,
    make_input_diagnostic,
    observation_sort_key,
)


def load_experiments(
    project_root: Path,
    configuration: ProjectConfiguration,
    reader: ExperimentSourceReader,
) -> ExperimentCatalog:
    """Read all declared sources and merge compatible fragments deterministically."""

    observations_by_run: dict[str, list[MetricObservation]] = defaultdict(list)
    metadata_by_run: dict[str, dict[str, ScalarValue]] = defaultdict(dict)
    sources_by_run: dict[str, set[str]] = defaultdict(set)
    config_by_run: dict[str, str | None] = {}
    diagnostics: list[InputDiagnostic] = []

    for source in sorted(configuration.sources, key=lambda item: (item.path, item.format.value)):
        result = reader.read(project_root, source)
        diagnostics.extend(result.diagnostics)
        for run in result.runs:
            sources_by_run[run.run_id].update(run.result_sources)
            _merge_metadata(run, metadata_by_run[run.run_id], diagnostics)
            _merge_config_reference(run, config_by_run, diagnostics)
            existing_metrics = {
                observation.metric_name for observation in observations_by_run[run.run_id]
            }
            for observation in run.observations:
                if observation.metric_name in existing_metrics:
                    diagnostics.append(
                        make_input_diagnostic(
                            code="MPE_DUPLICATE_METRIC",
                            severity=Severity.ERROR,
                            message=(
                                f"Run {run.run_id!r} defines metric "
                                f"{observation.metric_name!r} more than once."
                            ),
                            location=observation.location,
                            remediation=(
                                "Remove the duplicate metric or give it an explicit dimension."
                            ),
                            evidence_details=(
                                f"run_id={run.run_id}",
                                f"metric={observation.metric_name}",
                            ),
                        )
                    )
                    continue
                observations_by_run[run.run_id].append(observation)
                existing_metrics.add(observation.metric_name)

    runs = tuple(
        ExperimentRun(
            run_id=run_id,
            observations=tuple(sorted(observations, key=observation_sort_key)),
            metadata=tuple(sorted(metadata_by_run[run_id].items())),
            result_sources=tuple(sorted(sources_by_run[run_id])),
            config_reference=config_by_run.get(run_id),
            declared_commit=_scalar_text(metadata_by_run[run_id].get("commit")),
        )
        for run_id, observations in sorted(observations_by_run.items())
    )
    observations = tuple(
        sorted(
            (observation for run in runs for observation in run.observations),
            key=observation_sort_key,
        )
    )
    return ExperimentCatalog(
        runs=runs,
        observations=observations,
        diagnostics=tuple(sorted(diagnostics, key=diagnostic_sort_key)),
    )


def _merge_metadata(
    run: ExperimentRun,
    current: dict[str, ScalarValue],
    diagnostics: list[InputDiagnostic],
) -> None:
    for key, value in run.metadata:
        if key in current and current[key] != value:
            diagnostics.append(
                make_input_diagnostic(
                    code="MPE_METADATA_CONFLICT",
                    severity=Severity.ERROR,
                    message=f"Run {run.run_id!r} has conflicting metadata for {key!r}.",
                    location=run.observations[0].location,
                    remediation="Use one consistent metadata value for the run.",
                    evidence_details=(f"key={key}", f"first={current[key]!r}", f"next={value!r}"),
                )
            )
        else:
            current[key] = value


def _merge_config_reference(
    run: ExperimentRun,
    current: dict[str, str | None],
    diagnostics: list[InputDiagnostic],
) -> None:
    previous = current.get(run.run_id)
    if (
        previous is not None
        and run.config_reference is not None
        and previous != run.config_reference
    ):
        diagnostics.append(
            make_input_diagnostic(
                code="MPE_CONFIG_REFERENCE_CONFLICT",
                severity=Severity.ERROR,
                message=f"Run {run.run_id!r} has conflicting experiment config references.",
                location=run.observations[0].location,
                remediation="Declare one experiment configuration source for the run.",
                evidence_details=(f"first={previous}", f"next={run.config_reference}"),
            )
        )
    elif previous is None:
        current[run.run_id] = run.config_reference


def _scalar_text(value: ScalarValue) -> str | None:
    return None if value is None else str(value)
