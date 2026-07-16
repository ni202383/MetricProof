"""Application-level experiment source merge and diagnostic tests."""

from decimal import Decimal
from pathlib import Path

from metricproof.application.configuration import (
    ExperimentFormat,
    ExperimentSource,
    ProjectConfiguration,
)
from metricproof.application.experiments import load_experiments
from metricproof.application.ports import SourceReadResult
from metricproof.domain.models import ExperimentRun, MetricObservation, NumericValue, SourceLocation


class FakeReader:
    def __init__(self, results: dict[str, SourceReadResult]) -> None:
        self.results = results
        self.read_order: list[str] = []

    def read(self, project_root: Path, source: ExperimentSource) -> SourceReadResult:
        self.read_order.append(source.path)
        return self.results[source.path]


def _run(source: str, run_id: str, metric: str, value: str) -> ExperimentRun:
    location = SourceLocation(source, f"metrics.{metric}")
    observation = MetricObservation.create(
        run_id=run_id,
        metric_name=metric,
        numeric=NumericValue(value, Decimal(value)),
        source_file=source,
        source_selector=f"metrics.{metric}",
        location=location,
    )
    return ExperimentRun(
        run_id=run_id,
        observations=(observation,),
        metadata=(),
        result_sources=(source,),
    )


def test_load_experiments_uses_stable_source_order_and_merges_metrics(tmp_path: Path) -> None:
    sources = (
        ExperimentSource("z.json", ExperimentFormat.JSON),
        ExperimentSource("a.json", ExperimentFormat.JSON),
    )
    reader = FakeReader(
        {
            "a.json": SourceReadResult((_run("a.json", "run", "accuracy", "0.9"),)),
            "z.json": SourceReadResult((_run("z.json", "run", "loss", "0.1"),)),
        }
    )
    catalog = load_experiments(tmp_path, ProjectConfiguration("1", sources), reader)
    assert reader.read_order == ["a.json", "z.json"]
    assert [item.metric_name for item in catalog.runs[0].observations] == ["accuracy", "loss"]
    assert catalog.runs[0].result_sources == ("a.json", "z.json")


def test_load_experiments_reports_duplicate_metric(tmp_path: Path) -> None:
    sources = (
        ExperimentSource("a.json", ExperimentFormat.JSON),
        ExperimentSource("b.json", ExperimentFormat.JSON),
    )
    reader = FakeReader(
        {
            "a.json": SourceReadResult((_run("a.json", "run", "accuracy", "0.9"),)),
            "b.json": SourceReadResult((_run("b.json", "run", "accuracy", "0.8"),)),
        }
    )
    catalog = load_experiments(tmp_path, ProjectConfiguration("1", sources), reader)
    assert catalog.has_blocking_errors
    assert catalog.diagnostics[0].code == "MPE_DUPLICATE_METRIC"
