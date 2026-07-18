"""Strict, safe loading of .metricproof/config.yml."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from glob import has_magic
from pathlib import Path, PureWindowsPath
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from metricproof.adapters.config_claims import normalize_metric_aliases
from metricproof.adapters.limits import MAX_EXPERIMENT_SOURCES, MAX_FILE_BYTES
from metricproof.adapters.yaml_support import load_single_yaml
from metricproof.application.configuration import (
    CsvSourceOptions,
    ExperimentFormat,
    ExperimentSource,
    ProjectConfiguration,
    RulePolicy,
    StructuredSourceOptions,
)
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.domain.links import NumericTolerance
from metricproof.domain.models import Severity
from metricproof.domain.paper import LatexFormattingKind
from metricproof.domain.stage6 import (
    ComparisonSpec,
    MetricDirection,
    TableCheckSpec,
    TableMetricSpec,
)

CONFIG_RELATIVE_PATH = Path(".metricproof") / "config.yml"
SUPPORTED_SCHEMA_VERSION = "1"


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class _RawStructuredOptions(_StrictModel):
    metrics: dict[str, str]
    metadata: dict[str, str] = Field(default_factory=dict)
    records_selector: str | None = None
    run_id_selector: str | None = None


class _RawCsvOptions(_StrictModel):
    run_id_column: str
    metric_columns: list[str]
    metadata_columns: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_columns(self) -> _RawCsvOptions:
        metrics = set(self.metric_columns)
        metadata = set(self.metadata_columns)
        if not metrics:
            raise ValueError("metric_columns must contain at least one column")
        if len(metrics) != len(self.metric_columns):
            raise ValueError("metric_columns contains duplicates")
        if len(metadata) != len(self.metadata_columns):
            raise ValueError("metadata_columns contains duplicates")
        if metrics & metadata:
            raise ValueError("metric_columns and metadata_columns must not overlap")
        if self.run_id_column in metrics or self.run_id_column in metadata:
            raise ValueError("run_id_column must not also be a metric or metadata column")
        return self


class _RawSource(_StrictModel):
    path: str
    format: Literal["json", "yaml", "csv"]
    run_id: str | None = None
    structured: _RawStructuredOptions | None = None
    csv: _RawCsvOptions | None = None
    config_reference: str | None = None

    @model_validator(mode="after")
    def validate_format_options(self) -> _RawSource:
        if self.format == "csv":
            if self.csv is None or self.structured is not None:
                raise ValueError("CSV sources require csv options and forbid structured options")
            if self.run_id is not None:
                raise ValueError("CSV run IDs must come from run_id_column")
        else:
            if self.structured is None or self.csv is not None:
                raise ValueError(
                    "JSON/YAML sources require structured options and forbid csv options"
                )
            if not self.structured.metrics:
                raise ValueError("structured metrics must not be empty")
            if self.structured.records_selector is not None:
                if self.structured.run_id_selector is None or self.run_id is not None:
                    raise ValueError(
                        "record collections require run_id_selector and forbid a fixed run_id"
                    )
            elif (self.run_id is None) == (self.structured.run_id_selector is None):
                raise ValueError("declare exactly one of run_id or run_id_selector")
        return self


class _RawTolerance(_StrictModel):
    absolute: str
    relative: str


class _RawTolerances(_StrictModel):
    default: _RawTolerance
    metrics: dict[str, _RawTolerance] = Field(default_factory=dict)


class _RawTableMetric(_StrictModel):
    column: int = Field(ge=0)
    metric: str
    direction: Literal["higher", "lower"] | None = None


class _RawTableCheck(_StrictModel):
    table: str
    header_row: int = Field(ge=0)
    data_start_row: int = Field(ge=0)
    data_end_row: int | None = Field(default=None, ge=0)
    exclude_rows: list[int] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    label_column: int = Field(ge=0)
    metric_columns: list[_RawTableMetric]
    best_format: Literal["bold", "none"] = "bold"
    second_best_format: Literal["underline", "none"] = "underline"
    tie_tolerance: str = "0"

    @model_validator(mode="after")
    def validate_columns(self) -> _RawTableCheck:
        columns = [item.column for item in self.metric_columns]
        if not columns or len(columns) != len(set(columns)):
            raise ValueError("metric_columns must be non-empty and use unique columns")
        if self.label_column in columns:
            raise ValueError("label_column must not also be a metric column")
        if len(self.exclude_rows) != len(set(self.exclude_rows)):
            raise ValueError("exclude_rows contains duplicates")
        return self


class _RawComparison(_StrictModel):
    comparison_id: str
    baseline_run: str
    candidate_run: str
    controlled_keys: list[str]
    allowed_differences: dict[str, str] = Field(default_factory=dict)
    tolerances: dict[str, _RawTolerance] = Field(default_factory=dict)
    severity: Literal["info", "warning", "error"] = "warning"
    note: str = "Declared as a controlled condition in project configuration."

    @model_validator(mode="after")
    def validate_comparison(self) -> _RawComparison:
        if not self.controlled_keys or len(self.controlled_keys) != len(set(self.controlled_keys)):
            raise ValueError("controlled_keys must be non-empty and unique")
        if any(not value.strip() for value in self.allowed_differences.values()):
            raise ValueError("allowed_differences values must contain a reason")
        return self


class _RawPolicy(_StrictModel):
    include_possible_missing_provenance: bool = False
    missing_provenance_severity: Literal["info", "warning", "error"] = "warning"
    fail_on: Literal["info", "warning", "error"] = "error"


class _RawLimits(_StrictModel):
    max_file_bytes: int | None = None
    max_include_depth: int | None = None
    max_files: int | None = None


class _RawConfig(_StrictModel):
    schema_version: str
    claim_registry_path: str = ".metricproof/claims.yml"
    result_paths: list[_RawSource] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    experiment_config_paths: list[str] = Field(default_factory=list)
    exclude_paths: list[str] = Field(default_factory=list)
    paper_paths: list[str] = Field(default_factory=list)
    metric_aliases: dict[str, list[str]] = Field(default_factory=dict)
    metric_directions: dict[str, Literal["higher", "lower"]] = Field(default_factory=dict)
    table_checks: list[_RawTableCheck] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    numeric_tolerances: _RawTolerances | None = None
    controlled_config_keys: list[str] = Field(default_factory=list)
    ignored_claim_patterns: list[str] = Field(default_factory=list)
    comparisons: list[_RawComparison] = Field(default_factory=list)  # pyright: ignore[reportUnknownVariableType]
    policy: _RawPolicy | None = None
    limits: _RawLimits | None = None

    @model_validator(mode="after")
    def validate_stage6_ids(self) -> _RawConfig:
        table_refs = [item.table for item in self.table_checks]
        comparison_ids = [item.comparison_id for item in self.comparisons]
        if len(table_refs) != len(set(table_refs)):
            raise ValueError("table_checks contains duplicate table references")
        if len(comparison_ids) != len(set(comparison_ids)):
            raise ValueError("comparisons contains duplicate comparison_id values")
        return self


class YamlConfigurationRepository:
    """Load and validate project configuration without modifying the project."""

    def load(self, project_root: Path) -> ProjectConfiguration:
        root = project_root.resolve(strict=True)
        config_path = root / CONFIG_RELATIVE_PATH
        display_path = CONFIG_RELATIVE_PATH.as_posix()
        if not config_path.is_file():
            raise _config_error(
                display_path,
                "",
                "configuration file does not exist",
                "create .metricproof/config.yml in the project root",
            )
        resolved_config_path = config_path.resolve(strict=True)
        if not _is_within(resolved_config_path, root):
            raise _config_error(
                display_path,
                "",
                "configuration file escapes the project root through a symlink",
                "store config.yml inside the project root",
            )
        if resolved_config_path.stat().st_size > MAX_FILE_BYTES:
            raise _config_error(
                display_path,
                "",
                f"configuration exceeds {MAX_FILE_BYTES} bytes",
                "reduce the configuration size",
            )
        try:
            text = resolved_config_path.read_text(encoding="utf-8-sig")
        except UnicodeError as error:
            raise _config_error(
                display_path, "", f"configuration is not valid UTF-8: {error}", "save it as UTF-8"
            ) from error
        try:
            loaded = load_single_yaml(text, exact_numbers=False)
        except yaml.YAMLError as error:
            raise _config_error(
                display_path,
                "",
                f"invalid safe YAML: {error}",
                "fix the YAML syntax and remove unsafe or duplicate keys",
            ) from error
        try:
            raw = _RawConfig.model_validate(loaded)
        except ValidationError as error:
            first = error.errors(include_url=False)[0]
            field = ".".join(str(part) for part in first["loc"])
            raise _config_error(
                display_path,
                field,
                first["msg"],
                "use only documented fields and value types",
            ) from error
        if raw.schema_version != SUPPORTED_SCHEMA_VERSION:
            raise _config_error(
                display_path,
                "schema_version",
                f"unsupported schema version {raw.schema_version!r}",
                f"set schema_version to {SUPPORTED_SCHEMA_VERSION!r}",
            )

        claim_registry_path = _validate_relative_pattern(
            raw.claim_registry_path,
            display_path,
            "claim_registry_path",
        )
        if has_magic(claim_registry_path):
            raise _config_error(
                display_path,
                "claim_registry_path",
                "claim registry path must be an exact file, not a glob pattern",
                "use a path such as .metricproof/claims.yml",
            )
        if Path(claim_registry_path).suffix.casefold() not in {".yml", ".yaml"}:
            raise _config_error(
                display_path,
                "claim_registry_path",
                "claim registry path must use .yml or .yaml",
                "use a path such as .metricproof/claims.yml",
            )
        excludes = tuple(
            sorted(_validate_patterns(raw.exclude_paths, display_path, "exclude_paths"))
        )
        paper_paths: list[str] = []
        resolved_papers: set[Path] = set()
        for index, pattern in enumerate(raw.paper_paths):
            if has_magic(pattern):
                raise _config_error(
                    display_path,
                    f"paper_paths.{index}",
                    "paper_paths entries must be exact files, not glob patterns",
                    "declare each LaTeX entry file explicitly",
                )
            if Path(pattern.replace("\\", "/")).suffix.casefold() != ".tex":
                raise _config_error(
                    display_path,
                    f"paper_paths.{index}",
                    "paper entry files must use the .tex extension",
                    "declare a project-relative .tex entry file",
                )
            matches = _expand_files(
                root,
                pattern,
                excludes,
                display_path,
                f"paper_paths.{index}",
            )
            paper = matches[0]
            if paper in resolved_papers:
                raise _config_error(
                    display_path,
                    f"paper_paths.{index}",
                    f"paper entry resolves to an already declared file: {_relative(root, paper)}",
                    "remove the duplicate path alias",
                )
            resolved_papers.add(paper)
            paper_paths.append(_relative(root, paper))

        metric_aliases = normalize_metric_aliases(raw.metric_aliases, config_file=display_path)
        metric_directions = tuple(
            (name, MetricDirection(direction))
            for name, direction in sorted(raw.metric_directions.items())
        )
        table_checks = _build_table_checks(raw, display_path)
        comparisons = _build_comparisons(raw, display_path)
        rule_policy = _build_rule_policy(raw, display_path)
        sources: list[ExperimentSource] = []
        resolved_sources: set[Path] = set()
        for index, raw_source in enumerate(raw.result_paths):
            matches = _expand_files(
                root,
                raw_source.path,
                excludes,
                display_path,
                f"result_paths.{index}.path",
            )
            for path in matches:
                if path in resolved_sources:
                    raise _config_error(
                        display_path,
                        f"result_paths.{index}.path",
                        f"source resolves to an already declared file: {_relative(root, path)}",
                        "remove the duplicate path or overlapping glob",
                    )
                resolved_sources.add(path)
                sources.append(_build_source(root, path, raw_source, display_path, index))
                if len(sources) > MAX_EXPERIMENT_SOURCES:
                    raise _config_error(
                        display_path,
                        "result_paths",
                        f"more than {MAX_EXPERIMENT_SOURCES} source files matched",
                        "narrow the result path patterns",
                    )

        experiment_configs: set[str] = set()
        for index, pattern in enumerate(raw.experiment_config_paths):
            for path in _expand_files(
                root,
                pattern,
                excludes,
                display_path,
                f"experiment_config_paths.{index}",
            ):
                experiment_configs.add(_relative(root, path))

        return ProjectConfiguration(
            schema_version=raw.schema_version,
            sources=tuple(sorted(sources, key=lambda source: (source.path, source.format.value))),
            experiment_config_paths=tuple(sorted(experiment_configs)),
            exclude_paths=excludes,
            paper_paths=tuple(sorted(paper_paths)),
            metric_aliases=metric_aliases,
            metric_directions=metric_directions,
            table_checks=table_checks,
            comparisons=comparisons,
            claim_registry_path=claim_registry_path,
            rule_policy=rule_policy,
        )


def _build_table_checks(raw: _RawConfig, config_file: str) -> tuple[TableCheckSpec, ...]:
    result: list[TableCheckSpec] = []
    for index, item in enumerate(raw.table_checks):
        try:
            tolerance = Decimal(item.tie_tolerance)
            metrics = tuple(
                TableMetricSpec(
                    column=metric.column,
                    metric=metric.metric,
                    direction=MetricDirection(
                        metric.direction or raw.metric_directions.get(metric.metric, "")
                    ),
                )
                for metric in item.metric_columns
            )
            result.append(
                TableCheckSpec(
                    table=item.table,
                    header_row=item.header_row,
                    data_start_row=item.data_start_row,
                    data_end_row=item.data_end_row,
                    exclude_rows=tuple(sorted(item.exclude_rows)),
                    label_column=item.label_column,
                    metric_columns=metrics,
                    best_format=(LatexFormattingKind.BOLD if item.best_format == "bold" else None),
                    second_best_format=(
                        LatexFormattingKind.UNDERLINE
                        if item.second_best_format == "underline"
                        else None
                    ),
                    tie_tolerance=tolerance,
                )
            )
        except (InvalidOperation, ValueError) as error:
            raise _config_error(
                config_file,
                f"table_checks.{index}",
                f"invalid explicit table semantics: {error}",
                "declare valid columns, directions, formats, and a non-negative decimal tolerance",
            ) from error
    return tuple(sorted(result, key=lambda item: item.table))


def _build_comparisons(raw: _RawConfig, config_file: str) -> tuple[ComparisonSpec, ...]:
    result: list[ComparisonSpec] = []
    for index, item in enumerate(raw.comparisons):
        try:
            tolerances = tuple(
                (
                    key,
                    _numeric_tolerance(
                        tolerance,
                        config_file,
                        f"comparisons.{index}.tolerances.{key}",
                    ),
                )
                for key, tolerance in sorted(item.tolerances.items())
            )
            result.append(
                ComparisonSpec(
                    comparison_id=item.comparison_id,
                    baseline_run=item.baseline_run,
                    candidate_run=item.candidate_run,
                    controlled_keys=tuple(sorted(item.controlled_keys)),
                    allowed_differences=tuple(sorted(item.allowed_differences.items())),
                    tolerances=tolerances,
                    severity=Severity(item.severity),
                    note=item.note,
                )
            )
        except ValueError as error:
            raise _config_error(
                config_file,
                f"comparisons.{index}",
                f"invalid declared comparison: {error}",
                "use unique IDs, explicit runs, controlled keys, and reviewable reasons",
            ) from error
    return tuple(sorted(result, key=lambda item: item.comparison_id))


def _build_rule_policy(raw: _RawConfig, config_file: str) -> RulePolicy:
    default = NumericTolerance()
    metrics: tuple[tuple[str, NumericTolerance], ...] = ()
    if raw.numeric_tolerances is not None:
        default = _numeric_tolerance(
            raw.numeric_tolerances.default,
            config_file,
            "numeric_tolerances.default",
        )
        metrics = tuple(
            (
                metric,
                _numeric_tolerance(
                    tolerance,
                    config_file,
                    f"numeric_tolerances.metrics.{metric}",
                ),
            )
            for metric, tolerance in sorted(raw.numeric_tolerances.metrics.items())
        )
    policy = raw.policy or _RawPolicy()
    return RulePolicy(
        default_tolerance=default,
        metric_tolerances=metrics,
        include_possible_missing_provenance=policy.include_possible_missing_provenance,
        missing_provenance_severity=Severity(policy.missing_provenance_severity),
        fail_on=Severity(policy.fail_on),
    )


def _numeric_tolerance(
    raw: _RawTolerance,
    config_file: str,
    field: str,
) -> NumericTolerance:
    try:
        return NumericTolerance(
            absolute=Decimal(raw.absolute),
            relative=Decimal(raw.relative),
        )
    except (InvalidOperation, ValueError) as error:
        raise _config_error(
            config_file,
            field,
            f"numeric tolerance must contain finite non-negative decimals: {error}",
            "use quoted decimal strings such as absolute: '0.0001' and relative: '0'",
        ) from error


def find_project_root(start: Path) -> Path | None:
    """Find the nearest parent containing .metricproof/config.yml."""

    resolved = start.resolve()
    for candidate in (resolved, *resolved.parents):
        if (candidate / CONFIG_RELATIVE_PATH).is_file():
            return candidate
    return None


def _build_source(
    root: Path,
    path: Path,
    raw: _RawSource,
    config_file: str,
    index: int,
) -> ExperimentSource:
    config_reference = None
    if raw.config_reference is not None:
        config_path = _resolve_existing_file(
            root,
            raw.config_reference,
            config_file,
            f"result_paths.{index}.config_reference",
        )
        config_reference = _relative(root, config_path)
    structured = None
    if raw.structured is not None:
        structured = StructuredSourceOptions(
            metrics=tuple(sorted(raw.structured.metrics.items())),
            metadata=tuple(sorted(raw.structured.metadata.items())),
            records_selector=raw.structured.records_selector,
            run_id_selector=raw.structured.run_id_selector,
        )
    csv_options = None
    if raw.csv is not None:
        csv_options = CsvSourceOptions(
            run_id_column=raw.csv.run_id_column,
            metric_columns=tuple(raw.csv.metric_columns),
            metadata_columns=tuple(raw.csv.metadata_columns),
        )
    return ExperimentSource(
        path=_relative(root, path),
        format=ExperimentFormat(raw.format),
        run_id=raw.run_id,
        structured=structured,
        csv=csv_options,
        config_reference=config_reference,
    )


def _expand_files(
    root: Path,
    pattern: str,
    excludes: tuple[str, ...],
    config_file: str,
    field: str,
) -> tuple[Path, ...]:
    normalized = _validate_relative_pattern(pattern, config_file, field)
    candidates = root.glob(normalized) if has_magic(normalized) else (root / normalized,)
    matches: list[Path] = []
    for candidate in candidates:
        relative_hint = candidate.relative_to(root).as_posix()
        if any(Path(relative_hint).match(exclude) for exclude in excludes):
            continue
        if not candidate.exists():
            continue
        resolved = candidate.resolve(strict=True)
        if not _is_within(resolved, root):
            raise _config_error(
                config_file,
                field,
                f"path escapes the project root through a symlink: {pattern!r}",
                "use a file located inside the project root",
            )
        if not resolved.is_file():
            raise _config_error(
                config_file, field, f"path is not a file: {pattern!r}", "declare a regular file"
            )
        matches.append(resolved)
    if not matches:
        raise _config_error(
            config_file,
            field,
            f"path does not match an existing file: {pattern!r}",
            "correct the relative path or create the declared source",
        )
    return tuple(sorted(set(matches), key=lambda path: _relative(root, path)))


def _resolve_existing_file(root: Path, value: str, config_file: str, field: str) -> Path:
    matches = _expand_files(root, value, (), config_file, field)
    if len(matches) != 1:
        raise _config_error(
            config_file, field, "config_reference must resolve to one file", "use an exact path"
        )
    return matches[0]


def _validate_patterns(values: list[str], config_file: str, field: str) -> list[str]:
    return [
        _validate_relative_pattern(value, config_file, f"{field}.{index}")
        for index, value in enumerate(values)
    ]


def _validate_relative_pattern(value: str, config_file: str, field: str) -> str:
    if not value.strip():
        raise _config_error(config_file, field, "path must not be empty", "provide a relative path")
    windows = PureWindowsPath(value)
    path = Path(value)
    if path.is_absolute() or windows.is_absolute():
        raise _config_error(
            config_file,
            field,
            f"absolute paths are not allowed: {value!r}",
            "use a project-relative path",
        )
    normalized = value.replace("\\", "/")
    if ".." in Path(normalized).parts:
        raise _config_error(
            config_file,
            field,
            f"parent traversal is not allowed: {value!r}",
            "use a path contained in the project root",
        )
    return normalized


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _config_error(
    file: str, field: str, reason: str, remediation: str
) -> ProjectConfigurationError:
    return ProjectConfigurationError(
        file=file,
        field=field,
        reason=reason,
        remediation=remediation,
    )
