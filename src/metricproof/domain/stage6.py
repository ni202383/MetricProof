"""Pure Stage 6 table-mark and declared-comparison semantics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from metricproof.domain.diagnostics import (
    CheckDiagnostic,
    CheckDiagnosticKind,
    make_check_diagnostic,
    make_check_evidence,
)
from metricproof.domain.links import NumericTolerance
from metricproof.domain.models import Severity, SourceLocation
from metricproof.domain.paper import (
    LatexFormattingKind,
    LatexTable,
    LatexTableCell,
    LatexTableReliability,
)


class MetricDirection(StrEnum):
    HIGHER = "higher"
    LOWER = "lower"


@dataclass(frozen=True, slots=True)
class TableMetricSpec:
    column: int
    metric: str
    direction: MetricDirection

    def __post_init__(self) -> None:
        if self.column < 0 or not self.metric.strip():
            raise ValueError("table metric columns must be non-negative and named")


@dataclass(frozen=True, slots=True)
class TableCheckSpec:
    table: str
    header_row: int
    data_start_row: int
    label_column: int
    metric_columns: tuple[TableMetricSpec, ...]
    data_end_row: int | None = None
    exclude_rows: tuple[int, ...] = ()
    best_format: LatexFormattingKind | None = LatexFormattingKind.BOLD
    second_best_format: LatexFormattingKind | None = LatexFormattingKind.UNDERLINE
    tie_tolerance: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.table.strip():
            raise ValueError("table check references must not be empty")
        if min(self.header_row, self.data_start_row, self.label_column) < 0:
            raise ValueError("table row and column indexes must be non-negative")
        if self.data_end_row is not None and self.data_end_row < self.data_start_row:
            raise ValueError("table data_end_row must not precede data_start_row")
        if tuple(sorted(set(self.exclude_rows))) != self.exclude_rows:
            raise ValueError("excluded table rows must be unique and sorted")
        columns = tuple(item.column for item in self.metric_columns)
        if not columns or len(set(columns)) != len(columns):
            raise ValueError("table metric columns must be non-empty and unique")
        if self.label_column in columns:
            raise ValueError("table label column must not also be a metric column")
        if not self.tie_tolerance.is_finite() or self.tie_tolerance < 0:
            raise ValueError("table tie tolerance must be finite and non-negative")


class ConfigValueKind(StrEnum):
    NULL = "null"
    BOOLEAN = "boolean"
    STRING = "string"
    NUMBER = "number"
    LIST = "list"
    MAPPING = "mapping"


@dataclass(frozen=True, slots=True)
class ConfigValue:
    kind: ConfigValueKind
    scalar: str | bool | Decimal | None = None
    items: tuple[ConfigValue, ...] = ()
    entries: tuple[tuple[str, ConfigValue], ...] = ()

    def __post_init__(self) -> None:
        if self.kind is ConfigValueKind.LIST:
            if self.scalar is not None or self.entries:
                raise ValueError("list config values only contain items")
        elif self.kind is ConfigValueKind.MAPPING:
            if self.scalar is not None or self.items:
                raise ValueError("mapping config values only contain entries")
            if tuple(sorted(self.entries, key=lambda item: item[0])) != self.entries:
                raise ValueError("mapping config entries must use stable ordering")
            if len({key for key, _ in self.entries}) != len(self.entries):
                raise ValueError("mapping config keys must be unique")
        elif self.items or self.entries:
            raise ValueError("scalar config values cannot contain children")
        if self.kind is ConfigValueKind.NULL and self.scalar is not None:
            raise ValueError("null config values cannot carry a scalar")
        if self.kind is ConfigValueKind.NUMBER and not isinstance(self.scalar, Decimal):
            raise ValueError("number config values require Decimal")

    @property
    def display(self) -> str:
        if self.kind is ConfigValueKind.NULL:
            return "null"
        if self.kind is ConfigValueKind.BOOLEAN:
            return "true" if self.scalar else "false"
        if self.kind in {ConfigValueKind.STRING, ConfigValueKind.NUMBER}:
            return str(self.scalar)
        if self.kind is ConfigValueKind.LIST:
            return "[" + ", ".join(item.display for item in self.items) + "]"
        return "{" + ", ".join(f"{key}: {value.display}" for key, value in self.entries) + "}"


@dataclass(frozen=True, slots=True)
class ExperimentConfigSnapshot:
    run_id: str
    source_file: str
    values: tuple[tuple[str, ConfigValue | None], ...]

    def __post_init__(self) -> None:
        if not self.run_id.strip() or not self.source_file.strip():
            raise ValueError("config snapshots require run and project-relative source")
        if tuple(sorted(self.values, key=lambda item: item[0])) != self.values:
            raise ValueError("snapshot values must use stable key ordering")

    def value_for(self, key: str) -> ConfigValue | None:
        return next((value for name, value in self.values if name == key), None)


@dataclass(frozen=True, slots=True)
class ComparisonSpec:
    comparison_id: str
    baseline_run: str
    candidate_run: str
    controlled_keys: tuple[str, ...]
    allowed_differences: tuple[tuple[str, str], ...] = ()
    tolerances: tuple[tuple[str, NumericTolerance], ...] = ()
    severity: Severity = Severity.WARNING
    note: str = "Declared as a controlled condition in project configuration."

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.comparison_id, self.baseline_run, self.candidate_run)
        ):
            raise ValueError("comparison IDs and run IDs must not be empty")
        if (
            tuple(sorted(set(self.controlled_keys))) != self.controlled_keys
            or not self.controlled_keys
        ):
            raise ValueError("controlled keys must be non-empty, unique, and sorted")
        if tuple(sorted(self.allowed_differences)) != self.allowed_differences:
            raise ValueError("allowed differences must use stable ordering")
        if tuple(sorted(self.tolerances, key=lambda item: item[0])) != self.tolerances:
            raise ValueError("comparison tolerances must use stable ordering")
        if any(not reason.strip() for _, reason in self.allowed_differences):
            raise ValueError("allowed differences require a reviewable reason")
        if not self.note.strip():
            raise ValueError("comparisons require a review note")

    def tolerance_for(self, key: str) -> NumericTolerance:
        return next(
            (tolerance for name, tolerance in self.tolerances if name == key),
            NumericTolerance(),
        )


def table_reference(table: LatexTable) -> str:
    if table.label is not None and table.label.normalized_text.strip():
        return table.label.normalized_text.strip()
    if table.caption is not None and table.caption.normalized_text.strip():
        return f"{table.location.path}#caption:{table.caption.normalized_text.strip()}"
    start = table.location.char_start if table.location.char_start is not None else 0
    return f"{table.location.path}#char:{start}"


def check_wrong_best_mark(
    tables: tuple[LatexTable, ...], specs: tuple[TableCheckSpec, ...]
) -> tuple[CheckDiagnostic, ...]:
    diagnostics: list[CheckDiagnostic] = []
    by_reference = {table_reference(table): table for table in tables}
    for spec in specs:
        table = by_reference.get(spec.table)
        if table is None:
            diagnostics.append(_table_limitation(spec, None, "configured table was not found"))
            continue
        if table.reliability is not LatexTableReliability.PARSED:
            diagnostics.append(
                _table_limitation(spec, table, f"table reliability is {table.reliability.value}")
            )
            continue
        width = table.expected_column_count
        if (
            spec.header_row >= len(table.rows)
            or spec.data_start_row >= len(table.rows)
            or (spec.data_end_row is not None and spec.data_end_row > len(table.rows))
            or (
                width is not None
                and max(spec.label_column, *(item.column for item in spec.metric_columns)) >= width
            )
        ):
            diagnostics.append(
                _table_limitation(spec, table, "configured row or column is out of bounds")
            )
            continue
        for metric in spec.metric_columns:
            diagnostics.extend(_check_metric_column(table, spec, metric))
    return tuple(diagnostics)


def check_unfair_comparison(
    specs: tuple[ComparisonSpec, ...], snapshots: tuple[ExperimentConfigSnapshot, ...]
) -> tuple[CheckDiagnostic, ...]:
    by_run = {snapshot.run_id: snapshot for snapshot in snapshots}
    diagnostics: list[CheckDiagnostic] = []
    for spec in specs:
        baseline = by_run.get(spec.baseline_run)
        candidate = by_run.get(spec.candidate_run)
        if baseline is None or candidate is None:
            missing = spec.baseline_run if baseline is None else spec.candidate_run
            diagnostics.append(
                make_check_diagnostic(
                    kind=CheckDiagnosticKind.INPUT,
                    code="UNFAIR_COMPARISON",
                    severity=Severity.ERROR,
                    message=(
                        "A declared comparison could not be evaluated because a run or its "
                        "configuration snapshot is unavailable."
                    ),
                    location=SourceLocation(".metricproof/config.yml", selector=spec.comparison_id),
                    evidence=(
                        make_check_evidence(
                            kind="comparison_config",
                            summary=f"comparison={spec.comparison_id}; missing_run={missing}",
                        ),
                    ),
                    confidence=Decimal("1"),
                    remediation="Declare the run and its JSON/YAML config_reference, then retry.",
                    subject_id=f"comparison:{spec.comparison_id}",
                    observed=missing,
                    expected="available run configuration",
                )
            )
            continue
        allowed = dict(spec.allowed_differences)
        for key in spec.controlled_keys:
            left = baseline.value_for(key)
            right = candidate.value_for(key)
            if key in allowed:
                continue
            if left is None and right is None:
                diagnostics.append(_comparison_missing_key(spec, baseline, candidate, key))
                continue
            if _config_values_equal(left, right, spec.tolerance_for(key)):
                continue
            diagnostics.append(_comparison_difference(spec, baseline, candidate, key, left, right))
    return tuple(diagnostics)


def _check_metric_column(
    table: LatexTable, spec: TableCheckSpec, metric: TableMetricSpec
) -> tuple[CheckDiagnostic, ...]:
    rows = table.rows[spec.data_start_row : spec.data_end_row]
    rows = tuple(row for row in rows if row.row_index not in spec.exclude_rows)
    values: list[tuple[LatexTableCell, Decimal]] = []
    for row in rows:
        cell = next(
            (
                item
                for item in row.cells
                if item.logical_column_start
                <= metric.column
                < item.logical_column_start + item.logical_column_span
            ),
            None,
        )
        if cell is None:
            return (
                _table_limitation(spec, table, f"metric column {metric.column} is out of bounds"),
            )
        if not cell.numeric_references:
            continue
        if len(cell.numeric_references) != 1 or cell.logical_column_span != 1:
            return (
                _table_limitation(
                    spec,
                    table,
                    f"metric {metric.metric} contains an ambiguous multi-value or spanning cell",
                ),
            )
        remaining_commands = cell.raw_latex
        for supported_command in ("\\textbf", "\\underline", "\\pm", "\\%", "\\multicolumn"):
            remaining_commands = remaining_commands.replace(supported_command, "")
        if "\\" in remaining_commands:
            return (
                _table_limitation(
                    spec,
                    table,
                    f"metric {metric.metric} contains an unsupported formatting macro",
                ),
            )
        values.append((cell, cell.numeric_references[0].candidate.value.parsed))
    if not values:
        return ()
    best = _value_layer(values, metric.direction, spec.tie_tolerance)
    remaining = tuple(item for item in values if item not in best)
    second = _value_layer(remaining, metric.direction, spec.tie_tolerance) if remaining else ()
    diagnostics: list[CheckDiagnostic] = []
    for cell, value in values:
        formats = cell.numeric_references[0].formatting
        diagnostics.extend(
            _format_diagnostics(table, spec, metric, cell, value, formats, best, second)
        )
    return tuple(diagnostics)


def _value_layer(
    values: tuple[tuple[LatexTableCell, Decimal], ...] | list[tuple[LatexTableCell, Decimal]],
    direction: MetricDirection,
    tolerance: Decimal,
) -> tuple[tuple[LatexTableCell, Decimal], ...]:
    target = (
        max(value for _, value in values)
        if direction is MetricDirection.HIGHER
        else min(value for _, value in values)
    )
    return tuple(item for item in values if abs(item[1] - target) <= tolerance)


def _format_diagnostics(
    table: LatexTable,
    spec: TableCheckSpec,
    metric: TableMetricSpec,
    cell: LatexTableCell,
    value: Decimal,
    formats: tuple[LatexFormattingKind, ...],
    best: tuple[tuple[LatexTableCell, Decimal], ...],
    second: tuple[tuple[LatexTableCell, Decimal], ...],
) -> tuple[CheckDiagnostic, ...]:
    findings: list[tuple[str, LatexFormattingKind, bool]] = []
    if spec.best_format is not None:
        findings.append(("best", spec.best_format, any(item[0] is cell for item in best)))
    if spec.second_best_format is not None:
        findings.append(
            ("second-best", spec.second_best_format, any(item[0] is cell for item in second))
        )
    result: list[CheckDiagnostic] = []
    for rank, expected_format, belongs in findings:
        marked = expected_format in formats
        if marked == belongs:
            continue
        message = (
            f"The {expected_format.value} mark is missing for a {rank} value under the "
            "declared table semantics."
            if belongs
            else f"The {expected_format.value} mark is unexpected for a value outside the "
            f"{rank} set under the declared table semantics."
        )
        comparison = best if rank == "best" else second
        evidence = make_check_evidence(
            kind="table_comparison",
            summary=(
                f"table={table_reference(table)}; metric={metric.metric}; "
                f"direction={metric.direction.value}; rank={rank}"
            ),
            location=cell.location,
            details=tuple(
                f"{other.location.display} value={other_value}"
                for other, other_value in sorted(comparison, key=lambda item: item[0].location)
            ),
        )
        result.append(
            make_check_diagnostic(
                kind=CheckDiagnosticKind.RULE,
                code="WRONG_BEST_MARK",
                severity=Severity.WARNING,
                message=message,
                location=cell.location,
                evidence=(evidence,),
                confidence=Decimal("1"),
                remediation=(
                    "Review the displayed values and update the LaTeX formatting manually if the "
                    "declared table policy is intended."
                ),
                subject_id=f"table:{table_reference(table)}",
                observed=(
                    f"value={value}; formats={','.join(item.value for item in formats) or 'none'}"
                ),
                expected=f"{rank} uses {expected_format.value}",
                uncertainties=(
                    "This checks configured source formatting, not scientific quality.",
                ),
            )
        )
    return tuple(result)


def _table_limitation(
    spec: TableCheckSpec, table: LatexTable | None, reason: str
) -> CheckDiagnostic:
    location = (
        table.location
        if table is not None
        else SourceLocation(".metricproof/config.yml", selector=spec.table)
    )
    return make_check_diagnostic(
        kind=CheckDiagnosticKind.LIMITATION,
        code="WRONG_BEST_MARK",
        severity=Severity.WARNING,
        message="The configured table check was skipped because its structure is not reliable.",
        location=location,
        evidence=(make_check_evidence(kind="table_limitation", summary=reason, location=location),),
        confidence=Decimal("1"),
        remediation="Review the table structure or narrow the explicit table check configuration.",
        subject_id=f"table:{spec.table}",
        observed=reason,
        expected="reliably parsed configured table",
        uncertainties=(reason,),
    )


def _config_values_equal(
    left: ConfigValue | None, right: ConfigValue | None, tolerance: NumericTolerance
) -> bool:
    if left is None or right is None:
        return left is right
    if left.kind is not right.kind:
        return False
    if left.kind is ConfigValueKind.NUMBER:
        assert isinstance(left.scalar, Decimal) and isinstance(right.scalar, Decimal)
        effective = max(
            tolerance.absolute,
            tolerance.relative * max(abs(left.scalar), abs(right.scalar)),
        )
        return abs(left.scalar - right.scalar) <= effective
    return left == right


def _comparison_missing_key(
    spec: ComparisonSpec,
    baseline: ExperimentConfigSnapshot,
    candidate: ExperimentConfigSnapshot,
    key: str,
) -> CheckDiagnostic:
    location = SourceLocation(".metricproof/config.yml", selector=spec.comparison_id)
    return make_check_diagnostic(
        kind=CheckDiagnosticKind.INPUT,
        code="UNFAIR_COMPARISON",
        severity=Severity.ERROR,
        message="A declared controlled key is missing from both experiment configurations.",
        location=location,
        evidence=(
            make_check_evidence(
                kind="comparison_config",
                summary=f"comparison={spec.comparison_id}; missing_controlled_key={key}",
                details=(
                    f"baseline_source={baseline.source_file}",
                    f"candidate_source={candidate.source_file}",
                ),
            ),
        ),
        confidence=Decimal("1"),
        remediation="Add the controlled key to both configurations or remove it from the contract.",
        subject_id=f"comparison:{spec.comparison_id}",
        observed="missing on baseline and candidate",
        expected=f"controlled key {key}",
    )


def _comparison_difference(
    spec: ComparisonSpec,
    baseline: ExperimentConfigSnapshot,
    candidate: ExperimentConfigSnapshot,
    key: str,
    left: ConfigValue | None,
    right: ConfigValue | None,
) -> CheckDiagnostic:
    left_display = "<missing>" if left is None else left.display
    right_display = "<missing>" if right is None else right.display
    location = SourceLocation(candidate.source_file, selector=key)
    return make_check_diagnostic(
        kind=CheckDiagnosticKind.RULE,
        code="UNFAIR_COMPARISON",
        severity=spec.severity,
        message=(
            "A user-declared controlled condition differs between the baseline and candidate "
            "configurations and may require manual review."
        ),
        location=location,
        evidence=(
            make_check_evidence(
                kind="comparison_config",
                summary=f"comparison={spec.comparison_id}; controlled_key={key}",
                location=location,
                details=(
                    (
                        f"baseline={spec.baseline_run} source={baseline.source_file} "
                        f"value={left_display}"
                    ),
                    f"candidate={spec.candidate_run} source={candidate.source_file} "
                    f"value={right_display}",
                    f"reason={spec.note}",
                    "allowed_difference=false",
                ),
            ),
        ),
        confidence=Decimal("1"),
        remediation=(
            "Align the declared controlled condition or document an allowed difference with a "
            "specific reason."
        ),
        subject_id=f"comparison:{spec.comparison_id}",
        observed=f"{spec.candidate_run}: {right_display}",
        expected=f"{spec.baseline_run}: {left_display}",
        related_sources=(SourceLocation(baseline.source_file, selector=key),),
        uncertainties=("Matching configuration does not by itself prove a fair experiment.",),
    )
