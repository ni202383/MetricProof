"""Validated, adapter-neutral project configuration used by application services."""

from dataclasses import dataclass, field
from enum import StrEnum

from metricproof.domain.links import NumericTolerance
from metricproof.domain.models import Severity


class ExperimentFormat(StrEnum):
    JSON = "json"
    YAML = "yaml"
    CSV = "csv"


@dataclass(frozen=True, slots=True)
class StructuredSourceOptions:
    metrics: tuple[tuple[str, str], ...]
    metadata: tuple[tuple[str, str], ...] = ()
    records_selector: str | None = None
    run_id_selector: str | None = None


@dataclass(frozen=True, slots=True)
class CsvSourceOptions:
    run_id_column: str
    metric_columns: tuple[str, ...]
    metadata_columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExperimentSource:
    path: str
    format: ExperimentFormat
    run_id: str | None = None
    structured: StructuredSourceOptions | None = None
    csv: CsvSourceOptions | None = None
    config_reference: str | None = None


@dataclass(frozen=True, slots=True)
class RulePolicy:
    default_tolerance: NumericTolerance = field(default_factory=NumericTolerance)
    metric_tolerances: tuple[tuple[str, NumericTolerance], ...] = ()
    include_possible_missing_provenance: bool = False
    missing_provenance_severity: Severity = Severity.WARNING
    fail_on: Severity = Severity.ERROR

    def __post_init__(self) -> None:
        if (
            tuple(sorted(self.metric_tolerances, key=lambda item: item[0]))
            != self.metric_tolerances
        ):
            raise ValueError("metric tolerances must use stable metric-name ordering")
        names = tuple(item[0] for item in self.metric_tolerances)
        if len(set(names)) != len(names) or any(not name.strip() for name in names):
            raise ValueError("metric tolerance names must be non-empty and unique")

    def tolerance_for(self, metric_name: str) -> NumericTolerance:
        return next(
            (tolerance for name, tolerance in self.metric_tolerances if name == metric_name),
            self.default_tolerance,
        )


@dataclass(frozen=True, slots=True)
class ProjectConfiguration:
    schema_version: str
    sources: tuple[ExperimentSource, ...]
    experiment_config_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()
    paper_paths: tuple[str, ...] = ()
    metric_aliases: tuple[tuple[str, tuple[str, ...]], ...] = ()
    claim_registry_path: str = ".metricproof/claims.yml"
    rule_policy: RulePolicy = field(default_factory=RulePolicy)
