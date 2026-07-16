"""Safe local JSON, YAML, and CSV experiment result readers."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

import yaml

from metricproof.adapters.limits import MAX_CSV_ROWS, MAX_FILE_BYTES, MAX_NESTING_DEPTH
from metricproof.adapters.yaml_support import load_single_yaml
from metricproof.application.configuration import (
    CsvSourceOptions,
    ExperimentFormat,
    ExperimentSource,
    StructuredSourceOptions,
)
from metricproof.application.ports import SourceReadResult
from metricproof.domain.models import (
    ExperimentRun,
    InputDiagnostic,
    MetricObservation,
    ScalarValue,
    Severity,
    SourceLocation,
    make_input_diagnostic,
    observation_sort_key,
)
from metricproof.domain.numeric import DecimalToken, NumericParseError, parse_numeric


@dataclass(frozen=True, slots=True)
class _SourceProblem(Exception):
    code: str
    message: str
    selector: str = ""
    line: int | None = None
    column: int | None = None
    remediation: str = "Correct the declared experiment input."


class LocalExperimentSourceReader:
    """Read declared local result files without executing or importing them."""

    def read(self, project_root: Path, source: ExperimentSource) -> SourceReadResult:
        try:
            text = _read_source_text(project_root, source.path)
            if source.format is ExperimentFormat.JSON:
                return _read_json(text, source)
            if source.format is ExperimentFormat.YAML:
                return _read_yaml(text, source)
            if source.format is ExperimentFormat.CSV:
                return _read_csv(text, source)
            raise _SourceProblem(
                code="MPE_UNSUPPORTED_FORMAT",
                message=f"Unsupported experiment source format: {source.format!s}",
                remediation="Use json, yaml, or csv.",
            )
        except _SourceProblem as problem:
            return SourceReadResult((), (_diagnostic_from_problem(source.path, problem),))


def _read_source_text(project_root: Path, relative_path: str) -> str:
    root = project_root.resolve(strict=True)
    candidate = root / relative_path
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise _SourceProblem(
            code="MPE_SOURCE_NOT_FOUND",
            message=f"Experiment source does not exist: {relative_path}",
            remediation="Restore the file or correct result_paths in config.yml.",
        ) from error
    if not _is_within(resolved, root):
        raise _SourceProblem(
            code="MPE_PATH_ESCAPE",
            message=f"Experiment source escapes the project root: {relative_path}",
            remediation="Use a source located inside the project root.",
        )
    if not resolved.is_file():
        raise _SourceProblem(
            code="MPE_SOURCE_NOT_FILE",
            message=f"Experiment source is not a regular file: {relative_path}",
            remediation="Declare a regular JSON, YAML, or CSV file.",
        )
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise _SourceProblem(
            code="MPE_FILE_TOO_LARGE",
            message=f"Experiment source exceeds {MAX_FILE_BYTES} bytes: {relative_path}",
            remediation="Reduce or split the result file.",
        )
    try:
        return resolved.read_text(encoding="utf-8-sig")
    except UnicodeError as error:
        raise _SourceProblem(
            code="MPE_ENCODING_ERROR",
            message=f"Experiment source is not valid UTF-8: {error}",
            remediation="Save the source as UTF-8 or UTF-8 with BOM.",
        ) from error
    except OSError as error:
        raise _SourceProblem(
            code="MPE_SOURCE_READ_ERROR",
            message=f"Experiment source could not be read: {error}",
            remediation="Check local file permissions and path accessibility.",
        ) from error


def _read_json(text: str, source: ExperimentSource) -> SourceReadResult:
    try:
        parsed = cast(
            object,
            json.loads(
                text,
                parse_float=_json_decimal,
                parse_int=_json_decimal,
                parse_constant=_reject_json_constant,
                object_pairs_hook=_unique_json_object,
            ),
        )
    except json.JSONDecodeError as error:
        raise _SourceProblem(
            code="MPE_JSON_SYNTAX",
            message=f"Invalid JSON syntax: {error.msg}",
            line=error.lineno,
            column=error.colno,
            remediation="Fix the JSON syntax at the reported line and column.",
        ) from error
    except (ValueError, InvalidOperation) as error:
        raise _SourceProblem(
            code="MPE_JSON_VALUE",
            message=f"Invalid JSON value: {error}",
            remediation="Remove duplicate keys and non-finite numbers.",
        ) from error
    _validate_structure(parsed)
    return _read_structured(parsed, source)


def _read_yaml(text: str, source: ExperimentSource) -> SourceReadResult:
    try:
        parsed = load_single_yaml(text, exact_numbers=True)
    except yaml.YAMLError as error:
        mark = getattr(error, "problem_mark", None)
        line = cast(int | None, mark.line + 1 if mark is not None else None)
        column = cast(int | None, mark.column + 1 if mark is not None else None)
        recursive = "recursive" in str(error).casefold()
        raise _SourceProblem(
            code="MPE_RECURSIVE_STRUCTURE" if recursive else "MPE_YAML_SYNTAX",
            message=f"Invalid safe YAML: {error}",
            line=line,
            column=column,
            remediation=(
                "Fix the YAML syntax; remove duplicate keys, extra documents, or unsafe tags."
            ),
        ) from error
    _validate_structure(parsed)
    return _read_structured(parsed, source)


def _read_structured(parsed: object, source: ExperimentSource) -> SourceReadResult:
    options = source.structured
    if options is None:
        raise _SourceProblem(
            code="MPE_SOURCE_CONFIGURATION",
            message="Structured source options are missing.",
            remediation="Add structured metrics and run ID selection to config.yml.",
        )
    records = _structured_records(parsed, options)
    runs: list[ExperimentRun] = []
    diagnostics: list[InputDiagnostic] = []
    seen_run_ids: set[str] = set()

    for record, prefix in records:
        try:
            run_id = _structured_run_id(record, source, options, prefix)
        except _SourceProblem as problem:
            diagnostics.append(_diagnostic_from_problem(source.path, problem))
            continue
        if run_id in seen_run_ids:
            diagnostics.append(
                _make_error(
                    source.path,
                    "MPE_DUPLICATE_RUN_ID",
                    f"Run ID {run_id!r} occurs more than once in the source.",
                    prefix,
                    "Make each run_id unique within the source.",
                )
            )
            continue
        seen_run_ids.add(run_id)
        metadata, metadata_diagnostics = _structured_metadata(record, source.path, options, prefix)
        diagnostics.extend(metadata_diagnostics)
        observations: list[MetricObservation] = []
        for metric_name, selector in options.metrics:
            full_selector = _join_selector(prefix, selector)
            try:
                value = _select(record, selector)
                numeric = parse_numeric(value)
            except _SourceProblem as problem:
                diagnostics.append(_diagnostic_from_problem(source.path, problem, full_selector))
                continue
            except NumericParseError as error:
                diagnostics.append(
                    _make_error(
                        source.path,
                        "MPE_INVALID_NUMBER",
                        f"Metric {metric_name!r} is not a valid finite decimal: {error}",
                        full_selector,
                        "Provide a finite integer, decimal, or scientific-notation value.",
                    )
                )
                continue
            location = SourceLocation(path=source.path, selector=full_selector)
            observations.append(
                MetricObservation.create(
                    run_id=run_id,
                    metric_name=metric_name,
                    numeric=numeric,
                    source_file=source.path,
                    source_selector=full_selector,
                    location=location,
                    dataset=_metadata_string(metadata, "dataset"),
                    split=_metadata_string(metadata, "split"),
                    seed=_metadata_seed(metadata),
                    commit=_metadata_string(metadata, "commit"),
                    config_reference=source.config_reference,
                    metadata=tuple(sorted(metadata.items())),
                )
            )
        if observations:
            runs.append(
                ExperimentRun(
                    run_id=run_id,
                    observations=tuple(sorted(observations, key=observation_sort_key)),
                    metadata=tuple(sorted(metadata.items())),
                    result_sources=(source.path,),
                    config_reference=source.config_reference,
                    declared_commit=_metadata_string(metadata, "commit"),
                )
            )
    return SourceReadResult(
        runs=tuple(sorted(runs, key=lambda run: run.run_id)),
        diagnostics=tuple(diagnostics),
    )


def _structured_records(
    parsed: object,
    options: StructuredSourceOptions,
) -> tuple[tuple[Mapping[str, object], str], ...]:
    if options.records_selector is None:
        if not isinstance(parsed, Mapping):
            raise _SourceProblem(
                code="MPE_ROOT_TYPE",
                message="A single-run structured source must have a mapping root.",
                remediation="Use a mapping root or configure records_selector for an array.",
            )
        return ((cast(Mapping[str, object], parsed), ""),)
    selected = _select(parsed, options.records_selector)
    if isinstance(selected, str | bytes) or not isinstance(selected, Sequence):
        raise _SourceProblem(
            code="MPE_RECORDS_TYPE",
            message="records_selector must resolve to an array of mappings.",
            selector=options.records_selector,
            remediation="Point records_selector to the explicit run array.",
        )
    records: list[tuple[Mapping[str, object], str]] = []
    selected_records = cast(Sequence[object], selected)
    for index, record in enumerate(selected_records):
        prefix = _join_selector(options.records_selector, str(index))
        if not isinstance(record, Mapping):
            raise _SourceProblem(
                code="MPE_RECORD_TYPE",
                message="Each selected run record must be a mapping.",
                selector=prefix,
                remediation="Replace the array item with a mapping object.",
            )
        records.append((cast(Mapping[str, object], record), prefix))
    return tuple(records)


def _structured_run_id(
    record: Mapping[str, object],
    source: ExperimentSource,
    options: StructuredSourceOptions,
    prefix: str,
) -> str:
    if source.run_id is not None:
        return _normalize_run_id(source.run_id, prefix)
    if options.run_id_selector is None:
        raise _SourceProblem(
            code="MPE_RUN_ID_CONFIGURATION",
            message="No run ID selector was configured.",
            selector=prefix,
            remediation="Declare run_id or run_id_selector.",
        )
    value = _select(record, options.run_id_selector)
    return _normalize_run_id(value, _join_selector(prefix, options.run_id_selector))


def _normalize_run_id(value: object, selector: str) -> str:
    if (
        isinstance(value, bool)
        or value is None
        or (isinstance(value, Mapping | Sequence) and not isinstance(value, str))
    ):
        raise _SourceProblem(
            code="MPE_INVALID_RUN_ID",
            message="run_id must be a non-empty string or exact integer-like value.",
            selector=selector,
            remediation="Provide a stable scalar run_id.",
        )
    if isinstance(value, DecimalToken):
        normalized = value.raw_text
    elif isinstance(value, str | int | Decimal):
        normalized = str(value)
    else:
        raise _SourceProblem(
            code="MPE_INVALID_RUN_ID",
            message=f"Unsupported run_id type: {type(value).__name__}",
            selector=selector,
            remediation="Provide a stable scalar run_id.",
        )
    normalized = normalized.strip()
    if not normalized:
        raise _SourceProblem(
            code="MPE_MISSING_RUN_ID",
            message="run_id is empty.",
            selector=selector,
            remediation="Provide a non-empty run_id.",
        )
    return normalized


def _structured_metadata(
    record: Mapping[str, object],
    source_path: str,
    options: StructuredSourceOptions,
    prefix: str,
) -> tuple[dict[str, ScalarValue], tuple[InputDiagnostic, ...]]:
    metadata: dict[str, ScalarValue] = {}
    diagnostics: list[InputDiagnostic] = []
    for name, selector in options.metadata:
        full_selector = _join_selector(prefix, selector)
        try:
            metadata[name] = _metadata_scalar(_select(record, selector))
        except _SourceProblem as problem:
            diagnostics.append(_diagnostic_from_problem(source_path, problem, full_selector))
        except ValueError as error:
            diagnostics.append(
                _make_error(
                    source_path,
                    "MPE_INVALID_METADATA",
                    f"Metadata {name!r} is not a supported scalar: {error}",
                    full_selector,
                    "Use null, bool, string, integer, or finite decimal metadata.",
                )
            )
    return metadata, tuple(diagnostics)


def _read_csv(text: str, source: ExperimentSource) -> SourceReadResult:
    options = source.csv
    if options is None:
        raise _SourceProblem(
            code="MPE_SOURCE_CONFIGURATION",
            message="CSV source options are missing.",
            remediation="Declare run_id_column, metric_columns, and metadata_columns.",
        )
    try:
        rows = csv.reader(io.StringIO(text, newline=""), strict=True)
        header = next(rows, None)
        if header is None or not any(column.strip() for column in header):
            raise _SourceProblem(
                code="MPE_CSV_HEADER",
                message="CSV source is missing a header row.",
                line=1,
                remediation="Add one non-empty header row.",
            )
        _validate_csv_header(header, options)
        diagnostics: list[InputDiagnostic] = []
        declared = {options.run_id_column, *options.metric_columns, *options.metadata_columns}
        undeclared = tuple(column for column in header if column not in declared)
        if undeclared:
            diagnostics.append(
                make_input_diagnostic(
                    code="MPW_CSV_UNDECLARED_COLUMNS",
                    severity=Severity.WARNING,
                    message="CSV columns not declared by the source configuration are ignored.",
                    location=SourceLocation(path=source.path, line=1),
                    remediation="Declare needed columns or remove unused columns.",
                    evidence_details=tuple(f"ignored={column}" for column in undeclared),
                )
            )
        indexes = {column: index for index, column in enumerate(header)}
        runs: list[ExperimentRun] = []
        seen_run_ids: set[str] = set()
        for record_index, row in enumerate(rows, start=1):
            if record_index > MAX_CSV_ROWS:
                raise _SourceProblem(
                    code="MPE_CSV_ROW_LIMIT",
                    message=f"CSV source exceeds {MAX_CSV_ROWS} data rows.",
                    line=rows.line_num,
                    remediation="Split the CSV into smaller declared sources.",
                )
            line = rows.line_num
            if len(row) != len(header):
                diagnostics.append(
                    _make_error(
                        source.path,
                        "MPE_CSV_ROW_WIDTH",
                        f"CSV row has {len(row)} fields but the header has {len(header)}.",
                        "",
                        "Fix quoting or add/remove fields to match the header.",
                        line=line,
                    )
                )
                continue
            run_id = row[indexes[options.run_id_column]].strip()
            if not run_id:
                diagnostics.append(
                    _make_error(
                        source.path,
                        "MPE_MISSING_RUN_ID",
                        "CSV run_id is empty.",
                        f"column={options.run_id_column}",
                        "Provide a non-empty run_id.",
                        line=line,
                    )
                )
                continue
            if run_id in seen_run_ids:
                diagnostics.append(
                    _make_error(
                        source.path,
                        "MPE_DUPLICATE_RUN_ID",
                        f"CSV run_id {run_id!r} occurs more than once.",
                        f"column={options.run_id_column}",
                        "Make every CSV run_id unique.",
                        line=line,
                    )
                )
                continue
            seen_run_ids.add(run_id)
            metadata = {column: row[indexes[column]] for column in options.metadata_columns}
            observations: list[MetricObservation] = []
            for metric_name in options.metric_columns:
                raw_value = row[indexes[metric_name]]
                selector = f"row={line},column={metric_name}"
                try:
                    numeric = parse_numeric(raw_value)
                except NumericParseError as error:
                    diagnostics.append(
                        _make_error(
                            source.path,
                            "MPE_INVALID_NUMBER",
                            f"Metric {metric_name!r} is not a valid finite decimal: {error}",
                            selector,
                            "Provide a finite integer, decimal, or scientific-notation value.",
                            line=line,
                            column=indexes[metric_name] + 1,
                        )
                    )
                    continue
                location = SourceLocation(
                    path=source.path,
                    selector=selector,
                    line=line,
                    column=indexes[metric_name] + 1,
                )
                observations.append(
                    MetricObservation.create(
                        run_id=run_id,
                        metric_name=metric_name,
                        numeric=numeric,
                        source_file=source.path,
                        source_selector=selector,
                        location=location,
                        dataset=_metadata_string(metadata, "dataset"),
                        split=_metadata_string(metadata, "split"),
                        seed=_metadata_seed(metadata),
                        commit=_metadata_string(metadata, "commit"),
                        config_reference=source.config_reference,
                        metadata=tuple(sorted(metadata.items())),
                    )
                )
            if observations:
                runs.append(
                    ExperimentRun(
                        run_id=run_id,
                        observations=tuple(sorted(observations, key=observation_sort_key)),
                        metadata=tuple(sorted(metadata.items())),
                        result_sources=(source.path,),
                        config_reference=source.config_reference,
                        declared_commit=_metadata_string(metadata, "commit"),
                    )
                )
    except csv.Error as error:
        raise _SourceProblem(
            code="MPE_CSV_SYNTAX",
            message=f"Invalid CSV structure: {error}",
            remediation="Fix CSV quoting, delimiters, and line structure.",
        ) from error
    return SourceReadResult(
        runs=tuple(sorted(runs, key=lambda run: run.run_id)),
        diagnostics=tuple(diagnostics),
    )


def _validate_csv_header(header: list[str], options: CsvSourceOptions) -> None:
    if any(not column.strip() for column in header):
        raise _SourceProblem(
            code="MPE_CSV_HEADER",
            message="CSV header contains an empty column name.",
            line=1,
            remediation="Name every CSV column.",
        )
    duplicates = sorted({column for column in header if header.count(column) > 1})
    if duplicates:
        raise _SourceProblem(
            code="MPE_CSV_DUPLICATE_HEADER",
            message=f"CSV header contains duplicate columns: {', '.join(duplicates)}",
            line=1,
            remediation="Rename or remove duplicate header columns.",
        )
    missing = sorted(
        {options.run_id_column, *options.metric_columns, *options.metadata_columns} - set(header)
    )
    if missing:
        raise _SourceProblem(
            code="MPE_CSV_MISSING_COLUMN",
            message=f"CSV is missing configured columns: {', '.join(missing)}",
            line=1,
            remediation="Add the columns or correct the CSV source configuration.",
        )


def _json_decimal(raw_text: str) -> DecimalToken:
    return DecimalToken(raw_text=raw_text, value=Decimal(raw_text))


def _reject_json_constant(raw_text: str) -> object:
    raise ValueError(f"non-finite constant {raw_text!r} is not supported")


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def _validate_structure(value: object) -> None:
    active: set[int] = set()

    def visit(current: object, depth: int) -> None:
        if depth > MAX_NESTING_DEPTH:
            raise _SourceProblem(
                code="MPE_NESTING_LIMIT",
                message=f"Structured input exceeds nesting depth {MAX_NESTING_DEPTH}.",
                remediation="Flatten or simplify the result structure.",
            )
        if isinstance(current, Mapping):
            mapping = cast(Mapping[object, object], current)
            identity = id(mapping)
            if identity in active:
                raise _SourceProblem(
                    code="MPE_RECURSIVE_STRUCTURE",
                    message="Recursive mappings or YAML aliases are not supported.",
                    remediation="Replace recursive aliases with a finite mapping.",
                )
            active.add(identity)
            for key, nested in mapping.items():
                if not isinstance(key, str):
                    raise _SourceProblem(
                        code="MPE_NON_STRING_KEY",
                        message="Structured result mapping keys must be strings.",
                        remediation="Use string keys for selectors and metadata.",
                    )
                visit(nested, depth + 1)
            active.remove(identity)
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes):
            sequence = cast(Sequence[object], current)
            identity = id(sequence)
            if identity in active:
                raise _SourceProblem(
                    code="MPE_RECURSIVE_STRUCTURE",
                    message="Recursive arrays or YAML aliases are not supported.",
                    remediation="Replace recursive aliases with a finite array.",
                )
            active.add(identity)
            for nested in sequence:
                visit(nested, depth + 1)
            active.remove(identity)

    visit(value, 0)


def _select(value: object, selector: str) -> object:
    if not selector or any(not part for part in selector.split(".")):
        raise _SourceProblem(
            code="MPE_INVALID_SELECTOR",
            message=f"Selector is empty or malformed: {selector!r}",
            selector=selector,
            remediation="Use a non-empty dot path with explicit array indexes.",
        )
    current = value
    traversed: list[str] = []
    for part in selector.split("."):
        traversed.append(part)
        if isinstance(current, Mapping):
            if part not in current:
                raise _SourceProblem(
                    code="MPE_SELECTOR_NOT_FOUND",
                    message=f"Selector does not exist: {selector}",
                    selector=".".join(traversed),
                    remediation="Correct the selector or add the declared field.",
                )
            current = cast(Mapping[str, object], current)[part]
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes):
            sequence = cast(Sequence[object], current)
            try:
                index = int(part)
                current = sequence[index]
            except (ValueError, IndexError) as error:
                raise _SourceProblem(
                    code="MPE_SELECTOR_NOT_FOUND",
                    message=f"Array selector does not exist: {selector}",
                    selector=".".join(traversed),
                    remediation="Use an explicit in-range integer array index.",
                ) from error
        else:
            raise _SourceProblem(
                code="MPE_SELECTOR_TYPE",
                message=f"Selector traverses a scalar value: {selector}",
                selector=".".join(traversed),
                remediation="Point the selector through mappings or explicit array indexes.",
            )
    return current


def _metadata_scalar(value: object) -> ScalarValue:
    if isinstance(value, DecimalToken):
        return value.value
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("non-finite decimal")
        return value
    if value is None or isinstance(value, str | int | bool):
        return value
    if isinstance(value, float):
        raise ValueError("binary float metadata is not accepted")
    raise ValueError(type(value).__name__)


def _metadata_string(metadata: Mapping[str, ScalarValue], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    return str(value)


def _metadata_seed(metadata: Mapping[str, ScalarValue]) -> str | int | None:
    value = metadata.get("seed")
    if value is None:
        return None
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, int):
        return value
    if isinstance(value, Decimal) and value == value.to_integral_value():
        return int(value)
    return str(value)


def _join_selector(prefix: str, selector: str) -> str:
    return selector if not prefix else f"{prefix}.{selector}"


def _diagnostic_from_problem(
    source_path: str,
    problem: _SourceProblem,
    selector_override: str | None = None,
) -> InputDiagnostic:
    return _make_error(
        source_path,
        problem.code,
        problem.message,
        selector_override if selector_override is not None else problem.selector,
        problem.remediation,
        line=problem.line,
        column=problem.column,
    )


def _make_error(
    source_path: str,
    code: str,
    message: str,
    selector: str,
    remediation: str,
    *,
    line: int | None = None,
    column: int | None = None,
) -> InputDiagnostic:
    try:
        location = SourceLocation(
            path=source_path,
            selector=selector,
            line=line,
            column=column,
        )
    except ValueError:
        location = SourceLocation(
            path=".metricproof/config.yml",
            selector=f"result_path={source_path}",
        )
    return make_input_diagnostic(
        code=code,
        severity=Severity.ERROR,
        message=message,
        location=location,
        remediation=remediation,
        evidence_details=(f"source={source_path}", f"selector={selector}"),
    )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
