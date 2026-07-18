"""Load only configuration snapshots required by declared comparisons."""

from pathlib import Path

from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.ports import ExperimentConfigReader
from metricproof.domain.models import ExperimentCatalog, InputDiagnostic
from metricproof.domain.stage6 import ExperimentConfigSnapshot


def load_config_snapshots(
    project_root: Path,
    configuration: ProjectConfiguration,
    catalog: ExperimentCatalog,
    reader: ExperimentConfigReader,
) -> tuple[tuple[ExperimentConfigSnapshot, ...], tuple[InputDiagnostic, ...]]:
    keys_by_run: dict[str, set[str]] = {}
    for comparison in configuration.comparisons:
        for run_id in (comparison.baseline_run, comparison.candidate_run):
            keys_by_run.setdefault(run_id, set()).update(comparison.controlled_keys)

    snapshots: list[ExperimentConfigSnapshot] = []
    diagnostics: list[InputDiagnostic] = []
    runs = {run.run_id: run for run in catalog.runs}
    for run_id, keys in sorted(keys_by_run.items()):
        run = runs.get(run_id)
        if run is None or run.config_reference is None:
            continue
        result = reader.read(project_root, run, tuple(sorted(keys)))
        snapshots.extend(result.snapshots)
        diagnostics.extend(result.diagnostics)
    return (
        tuple(sorted(snapshots, key=lambda item: item.run_id)),
        tuple(diagnostics),
    )
