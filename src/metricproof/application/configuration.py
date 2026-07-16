"""Validated, adapter-neutral project configuration used by application services."""

from dataclasses import dataclass
from enum import StrEnum


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
class ProjectConfiguration:
    schema_version: str
    sources: tuple[ExperimentSource, ...]
    experiment_config_paths: tuple[str, ...] = ()
    exclude_paths: tuple[str, ...] = ()
