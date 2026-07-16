"""Deterministic, non-executing LaTeX table structure parsing."""

from __future__ import annotations

import re
from bisect import bisect_left
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import cast

from metricproof.adapters.limits import (
    MAX_LATEX_CELL_CHARS,
    MAX_LATEX_MULTICOLUMN_SPAN,
    MAX_LATEX_ROW_CELLS,
    MAX_LATEX_TABLE_CELLS,
    MAX_LATEX_TABLE_NESTING_DEPTH,
    MAX_LATEX_TABLE_ROWS,
    MAX_LATEX_TABLES,
)
from metricproof.domain.models import (
    DiagnosticKind,
    InputDiagnostic,
    Severity,
    SourceLocation,
    diagnostic_sort_key,
    make_input_diagnostic,
)
from metricproof.domain.paper import (
    LatexCellFormatting,
    LatexCellNumericReference,
    LatexColumnSpec,
    LatexFormattingKind,
    LatexTable,
    LatexTableCell,
    LatexTableKind,
    LatexTableReliability,
    LatexTableRow,
    LatexTableStructureKind,
    LatexTableStructureMarker,
    LatexTableText,
    RawNumericCandidate,
    candidate_sort_key,
    formatting_sort_key,
    structure_marker_sort_key,
    table_sort_key,
)

_SUPPORTED_ENVIRONMENTS = frozenset({"tabular", "tabular*"})
_CONTAINER_ENVIRONMENTS = frozenset({"table", "table*"})
_UNSUPPORTED_ENVIRONMENTS = frozenset({"longtable", "tabularx", "array", "matrix", "aligned"})
_TABLE_ENVIRONMENTS = _SUPPORTED_ENVIRONMENTS | _CONTAINER_ENVIRONMENTS | _UNSUPPORTED_ENVIRONMENTS
_FORMATTING_COMMANDS = {
    "textbf": LatexFormattingKind.BOLD,
    "underline": LatexFormattingKind.UNDERLINE,
}
_STRUCTURE_COMMANDS = {
    "hline": LatexTableStructureKind.HLINE,
    "cline": LatexTableStructureKind.CLINE,
    "toprule": LatexTableStructureKind.TOPRULE,
    "midrule": LatexTableStructureKind.MIDRULE,
    "bottomrule": LatexTableStructureKind.BOTTOMRULE,
    "cmidrule": LatexTableStructureKind.CMIDRULE,
    "addlinespace": LatexTableStructureKind.ADDLINESPACE,
}
_MULTICOLUMN_COUNT_RE = re.compile(r"[1-9][0-9]*")
_ESCAPED_TEXT_SYMBOLS = frozenset({"&", "%", "_", "#", "{", "}", "$"})

type _LocationFactory = Callable[[int, int], SourceLocation]


@dataclass(frozen=True, slots=True)
class TableParseResult:
    tables: tuple[LatexTable, ...]
    diagnostics: tuple[InputDiagnostic, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class _Argument:
    start: int
    content_start: int
    content_end: int
    end: int


@dataclass(frozen=True, slots=True)
class _OpenEnvironment:
    name: str
    start: int
    body_start: int
    parent_start: int | None


@dataclass(frozen=True, slots=True)
class _EnvironmentSpan:
    name: str
    start: int
    body_start: int
    end_start: int
    end: int
    parent_start: int | None
    closed: bool


@dataclass(frozen=True, slots=True)
class _EnvironmentScan:
    spans: tuple[_EnvironmentSpan, ...]
    diagnostics: tuple[InputDiagnostic, ...]
    complete: bool


@dataclass(frozen=True, slots=True)
class _ContainerMetadata:
    caption: LatexTableText | None
    label: LatexTableText | None
    diagnostics: tuple[InputDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class _TabularPreamble:
    column_spec: LatexColumnSpec | None
    body_start: int
    diagnostics: tuple[InputDiagnostic, ...]


@dataclass(frozen=True, slots=True)
class _RawRow:
    start: int
    end: int
    cells: tuple[tuple[int, int], ...]
    markers: tuple[LatexTableStructureMarker, ...]
    marker_ranges: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class _RowsResult:
    rows: tuple[LatexTableRow, ...]
    trailing_markers: tuple[LatexTableStructureMarker, ...]
    diagnostics: tuple[InputDiagnostic, ...]
    degraded: bool
    stopped_by_limit: bool


@dataclass(frozen=True, slots=True)
class _CellShape:
    content_start: int
    content_end: int
    logical_span: int
    multicolumn_format: str | None
    limitations: tuple[str, ...]
    diagnostics: tuple[InputDiagnostic, ...]
    stopped_by_limit: bool = False


class _CandidateIndex:
    def __init__(self, candidates: tuple[RawNumericCandidate, ...]) -> None:
        pairs = sorted(
            (
                (item.location.char_start, item)
                for item in candidates
                if item.location.char_start is not None and item.location.char_end is not None
            ),
            key=lambda item: (item[0], candidate_sort_key(item[1])),
        )
        self._starts = tuple(item[0] for item in pairs)
        self._candidates = tuple(item[1] for item in pairs)

    def within(self, start: int, end: int) -> tuple[RawNumericCandidate, ...]:
        index = bisect_left(self._starts, start)
        found: list[RawNumericCandidate] = []
        while index < len(self._candidates):
            candidate = self._candidates[index]
            candidate_start = cast(int, candidate.location.char_start)
            candidate_end = cast(int, candidate.location.char_end)
            if candidate_start > end:
                break
            if candidate_start >= start and candidate_end <= end:
                found.append(candidate)
            index += 1
        return tuple(found)


def parse_latex_tables(
    text: str,
    masked_text: str,
    path: str,
    candidates: tuple[RawNumericCandidate, ...],
    location_for: _LocationFactory,
) -> TableParseResult:
    """Parse bounded structures from one already-read LaTeX document."""

    if len(text) != len(masked_text):
        raise ValueError("masked source must preserve original character length")
    environment_scan = _scan_environments(masked_text, location_for)
    data_spans = tuple(
        span
        for span in environment_scan.spans
        if span.name in _SUPPORTED_ENVIRONMENTS | _UNSUPPORTED_ENVIRONMENTS
    )
    diagnostics = list(environment_scan.diagnostics)
    complete = environment_scan.complete
    if len(data_spans) > MAX_LATEX_TABLES:
        overflow = data_spans[MAX_LATEX_TABLES]
        diagnostics.append(
            _input_diagnostic(
                code="MPE_LATEX_TABLE_LIMIT",
                severity=Severity.ERROR,
                message=f"LaTeX tables exceed the fixed limit {MAX_LATEX_TABLES}.",
                location=location_for(overflow.start, overflow.end),
                remediation="reduce or split the number of tables",
            )
        )
        data_spans = data_spans[:MAX_LATEX_TABLES]
        complete = False

    candidate_index = _CandidateIndex(candidates)
    metadata_cache: dict[int, _ContainerMetadata] = {}
    tables: list[LatexTable] = []
    for span in data_spans:
        container = _find_container(span, environment_scan.spans)
        metadata = _ContainerMetadata(None, None, ())
        if container is not None:
            metadata = metadata_cache.get(container.start) or _parse_container_metadata(
                text, masked_text, container, environment_scan.spans, location_for
            )
            metadata_cache[container.start] = metadata
        related = _diagnostics_for_span(
            environment_scan.diagnostics, container if container is not None else span
        )
        if span.name in _UNSUPPORTED_ENVIRONMENTS:
            table = _unsupported_table(span, container, metadata, related, location_for)
        else:
            table = _supported_table(
                text,
                masked_text,
                span,
                container,
                metadata,
                related,
                candidate_index,
                location_for,
            )
        tables.append(table)
        diagnostics.extend(table.diagnostics)
        if table.reliability is not LatexTableReliability.PARSED:
            complete = False

    unique = {item.diagnostic_id: item for item in diagnostics}
    return TableParseResult(
        tables=tuple(sorted(tables, key=table_sort_key)),
        diagnostics=tuple(sorted(unique.values(), key=diagnostic_sort_key)),
        complete=complete,
    )


def _scan_environments(
    source: str,
    location_for: _LocationFactory,
) -> _EnvironmentScan:
    stack: list[_OpenEnvironment] = []
    spans: list[_EnvironmentSpan] = []
    diagnostics: list[InputDiagnostic] = []
    complete = True
    index = 0
    while index < len(source):
        if source[index] != "\\":
            index += 1
            continue
        command, command_end = _read_command(source, index)
        if command not in {"begin", "end"}:
            index = command_end
            continue
        argument = _read_group(source, command_end)
        if argument is None:
            index = command_end
            continue
        name = source[argument.content_start : argument.content_end].strip()
        if command == "begin":
            if name in _TABLE_ENVIRONMENTS:
                table_depth = sum(item.name in _TABLE_ENVIRONMENTS for item in stack)
                if table_depth >= MAX_LATEX_TABLE_NESTING_DEPTH:
                    diagnostics.append(
                        _input_diagnostic(
                            code="MPE_LATEX_TABLE_NESTING_DEPTH",
                            severity=Severity.ERROR,
                            message=(
                                "LaTeX table nesting exceeds the fixed limit "
                                f"{MAX_LATEX_TABLE_NESTING_DEPTH}."
                            ),
                            location=location_for(index, argument.end),
                            remediation="reduce nested table environments",
                            details=(f"environment={name}",),
                        )
                    )
                    complete = False
                if name in _SUPPORTED_ENVIRONMENTS and any(
                    item.name in _SUPPORTED_ENVIRONMENTS for item in stack
                ):
                    diagnostics.append(
                        _limitation_diagnostic(
                            code="MPW_LATEX_NESTED_TABULAR",
                            message="A nested tabular was retained with degraded reliability.",
                            location=location_for(index, argument.end),
                            remediation="flatten nested tabular environments",
                            details=(f"environment={name}",),
                        )
                    )
                    complete = False
            stack.append(
                _OpenEnvironment(
                    name=name,
                    start=index,
                    body_start=argument.end,
                    parent_start=stack[-1].start if stack else None,
                )
            )
            index = argument.end
            continue

        match_index = next(
            (
                position
                for position in range(len(stack) - 1, -1, -1)
                if stack[position].name == name
            ),
            None,
        )
        if match_index is None:
            if name in _TABLE_ENVIRONMENTS:
                diagnostics.append(
                    _limitation_diagnostic(
                        code="MPW_LATEX_UNEXPECTED_TABLE_END",
                        message=f"Unexpected \\end{{{name}}} has no matching begin.",
                        location=location_for(index, argument.end),
                        remediation="remove the end command or add its matching begin",
                        details=(f"environment={name}",),
                    )
                )
                complete = False
            index = argument.end
            continue

        for opened in reversed(stack[match_index + 1 :]):
            spans.append(
                _EnvironmentSpan(
                    name=opened.name,
                    start=opened.start,
                    body_start=opened.body_start,
                    end_start=index,
                    end=index,
                    parent_start=opened.parent_start,
                    closed=False,
                )
            )
            if opened.name in _TABLE_ENVIRONMENTS:
                diagnostics.append(_unclosed_environment(opened, location_for))
                complete = False
        opened = stack[match_index]
        del stack[match_index:]
        spans.append(
            _EnvironmentSpan(
                name=opened.name,
                start=opened.start,
                body_start=opened.body_start,
                end_start=index,
                end=argument.end,
                parent_start=opened.parent_start,
                closed=True,
            )
        )
        index = argument.end

    for opened in reversed(stack):
        spans.append(
            _EnvironmentSpan(
                name=opened.name,
                start=opened.start,
                body_start=opened.body_start,
                end_start=len(source),
                end=len(source),
                parent_start=opened.parent_start,
                closed=False,
            )
        )
        if opened.name in _TABLE_ENVIRONMENTS:
            diagnostics.append(_unclosed_environment(opened, location_for))
            complete = False
    return _EnvironmentScan(
        spans=tuple(sorted(spans, key=lambda item: (item.start, item.end, item.name))),
        diagnostics=tuple(sorted(diagnostics, key=diagnostic_sort_key)),
        complete=complete,
    )


def _unclosed_environment(
    opened: _OpenEnvironment,
    location_for: _LocationFactory,
) -> InputDiagnostic:
    return _limitation_diagnostic(
        code="MPW_LATEX_UNCLOSED_TABLE_ENVIRONMENT",
        message=f"Unclosed {opened.name} was retained through its recovery boundary.",
        location=location_for(opened.start, opened.body_start),
        remediation=f"add \\end{{{opened.name}}}",
        details=(f"environment={opened.name}",),
    )


def _find_container(
    span: _EnvironmentSpan,
    spans: tuple[_EnvironmentSpan, ...],
) -> _EnvironmentSpan | None:
    containers = [
        candidate
        for candidate in spans
        if candidate.name in _CONTAINER_ENVIRONMENTS
        and candidate.start < span.start
        and candidate.end >= span.end
    ]
    return max(containers, key=lambda item: item.start, default=None)


def _parse_container_metadata(
    text: str,
    source: str,
    container: _EnvironmentSpan,
    spans: tuple[_EnvironmentSpan, ...],
    location_for: _LocationFactory,
) -> _ContainerMetadata:
    caption: LatexTableText | None = None
    label: LatexTableText | None = None
    diagnostics: list[InputDiagnostic] = []
    child_ranges = tuple(
        sorted(
            (
                (span.start, span.end)
                for span in spans
                if span.name in _TABLE_ENVIRONMENTS
                and span.start > container.start
                and span.end <= container.end_start
            ),
            key=lambda item: item[0],
        )
    )
    index = container.body_start
    brace_depth = 0
    child_index = 0
    while index < container.end_start:
        while child_index < len(child_ranges) and child_ranges[child_index][1] <= index:
            child_index += 1
        if child_index < len(child_ranges):
            child_start, child_end = child_ranges[child_index]
            if child_start <= index < child_end:
                index = child_end
                continue
        character = source[index]
        if character == "{" and not _is_escaped(source, index):
            brace_depth += 1
            index += 1
            continue
        if character == "}" and not _is_escaped(source, index):
            brace_depth = max(0, brace_depth - 1)
            index += 1
            continue
        if character != "\\" or brace_depth:
            index += 1
            continue
        command, command_end = _read_command(source, index)
        if command not in {"caption", "label"}:
            index = command_end
            continue
        argument_start = command_end
        if command == "caption":
            optional = _read_group(source, argument_start, "[", "]")
            if optional is not None:
                argument_start = optional.end
        argument = _read_group(source, argument_start)
        if argument is None or argument.end > container.end_start:
            diagnostics.append(
                _limitation_diagnostic(
                    code=(
                        "MPW_LATEX_CAPTION_INVALID"
                        if command == "caption"
                        else "MPW_LATEX_LABEL_INVALID"
                    ),
                    message=f"\\{command} is missing a closed braced argument.",
                    location=location_for(index, command_end),
                    remediation=f"use \\{command}{{...}} with a closed argument",
                )
            )
            index = command_end
            continue
        raw = text[argument.content_start : argument.content_end]
        value = LatexTableText(
            raw_text=raw,
            normalized_text=_normalize_text(source, argument.content_start, argument.content_end),
            location=location_for(argument.content_start, argument.content_end),
        )
        if command == "caption":
            if caption is None:
                caption = value
            else:
                diagnostics.append(
                    _limitation_diagnostic(
                        code="MPW_LATEX_DUPLICATE_CAPTION",
                        message="Multiple captions in one table container are ambiguous.",
                        location=location_for(index, argument.end),
                        remediation="keep one caption per table container",
                    )
                )
        elif label is None:
            label = value
        else:
            diagnostics.append(
                _limitation_diagnostic(
                    code="MPW_LATEX_DUPLICATE_LABEL",
                    message="Multiple labels in one table container are ambiguous.",
                    location=location_for(index, argument.end),
                    remediation="keep one label per table container",
                )
            )
        index = argument.end
    return _ContainerMetadata(
        caption=caption,
        label=label,
        diagnostics=tuple(sorted(diagnostics, key=diagnostic_sort_key)),
    )


def _supported_table(
    text: str,
    source: str,
    span: _EnvironmentSpan,
    container: _EnvironmentSpan | None,
    metadata: _ContainerMetadata,
    related_diagnostics: tuple[InputDiagnostic, ...],
    candidate_index: _CandidateIndex,
    location_for: _LocationFactory,
) -> LatexTable:
    preamble = _parse_tabular_preamble(text, source, span, location_for)
    rows = _parse_rows(
        text,
        source,
        preamble.body_start,
        span.end_start,
        preamble.column_spec.expected_column_count if preamble.column_spec else None,
        candidate_index,
        location_for,
    )
    diagnostics = tuple(
        sorted(
            {
                item.diagnostic_id: item
                for item in (
                    *related_diagnostics,
                    *metadata.diagnostics,
                    *preamble.diagnostics,
                    *rows.diagnostics,
                )
            }.values(),
            key=diagnostic_sort_key,
        )
    )
    reliability = (
        LatexTableReliability.DEGRADED
        if diagnostics or rows.degraded or not span.closed
        else LatexTableReliability.PARSED
    )
    return LatexTable(
        environment=LatexTableKind(span.name),
        location=location_for(span.start, span.end),
        container_environment=LatexTableKind(container.name) if container else None,
        container_location=location_for(container.start, container.end) if container else None,
        caption=metadata.caption,
        label=metadata.label,
        column_spec=preamble.column_spec,
        rows=rows.rows,
        structure_markers=rows.trailing_markers,
        diagnostics=diagnostics,
        reliability=reliability,
    )


def _unsupported_table(
    span: _EnvironmentSpan,
    container: _EnvironmentSpan | None,
    metadata: _ContainerMetadata,
    related_diagnostics: tuple[InputDiagnostic, ...],
    location_for: _LocationFactory,
) -> LatexTable:
    unsupported = _limitation_diagnostic(
        code="MPW_LATEX_UNSUPPORTED_TABLE_ENVIRONMENT",
        message=f"The {span.name} environment is recognized but not parsed as tabular.",
        location=location_for(span.start, span.end),
        remediation="use tabular/tabular* or review this structure manually",
        details=(f"environment={span.name}",),
    )
    diagnostics = tuple(
        sorted(
            {
                item.diagnostic_id: item
                for item in (*related_diagnostics, *metadata.diagnostics, unsupported)
            }.values(),
            key=diagnostic_sort_key,
        )
    )
    return LatexTable(
        environment=LatexTableKind(span.name),
        location=location_for(span.start, span.end),
        container_environment=LatexTableKind(container.name) if container else None,
        container_location=location_for(container.start, container.end) if container else None,
        caption=metadata.caption,
        label=metadata.label,
        column_spec=None,
        rows=(),
        structure_markers=(),
        diagnostics=diagnostics,
        reliability=LatexTableReliability.UNSUPPORTED,
    )


def _parse_tabular_preamble(
    text: str,
    source: str,
    span: _EnvironmentSpan,
    location_for: _LocationFactory,
) -> _TabularPreamble:
    index = span.body_start
    diagnostics: list[InputDiagnostic] = []
    if span.name == "tabular*":
        width = _read_group(source, index)
        if width is None:
            diagnostics.append(
                _limitation_diagnostic(
                    code="MPW_LATEX_COLUMN_SPEC_INVALID",
                    message="tabular* is missing its required width argument.",
                    location=location_for(span.start, span.body_start),
                    remediation="use \\begin{tabular*}{width}{columns}",
                )
            )
            return _TabularPreamble(None, span.body_start, tuple(diagnostics))
        index = width.end
    optional = _read_group(source, index, "[", "]")
    if optional is not None:
        index = optional.end
    specification = _read_group(source, index)
    if specification is None or specification.end > span.end_start:
        diagnostics.append(
            _limitation_diagnostic(
                code="MPW_LATEX_COLUMN_SPEC_INVALID",
                message=f"{span.name} is missing a closed column specification.",
                location=location_for(span.start, span.body_start),
                remediation="provide a literal braced column specification",
            )
        )
        return _TabularPreamble(None, span.body_start, tuple(diagnostics))
    expected = _count_columns(source, specification.content_start, specification.content_end)
    if expected is None:
        diagnostics.append(
            _limitation_diagnostic(
                code="MPW_LATEX_COLUMN_SPEC_UNAVAILABLE",
                message="The column specification is outside the supported basic subset.",
                location=location_for(specification.start, specification.end),
                remediation="use basic l/c/r/p/m/b columns or review the count manually",
            )
        )
    return _TabularPreamble(
        column_spec=LatexColumnSpec(
            raw_latex=text[specification.start : specification.end],
            location=location_for(specification.start, specification.end),
            expected_column_count=expected,
        ),
        body_start=specification.end,
        diagnostics=tuple(sorted(diagnostics, key=diagnostic_sort_key)),
    )


def _count_columns(source: str, start: int, end: int, *, depth: int = 0) -> int | None:
    if depth >= MAX_LATEX_TABLE_NESTING_DEPTH:
        return None
    count = 0
    index = start
    while index < end:
        character = source[index]
        if character.isspace() or character == "|":
            index += 1
            continue
        if character in {"l", "c", "r"}:
            count += 1
            index += 1
            continue
        if character in {"p", "m", "b"}:
            argument = _read_group(source, index + 1)
            if argument is None or argument.end > end:
                return None
            count += 1
            index = argument.end
            continue
        if character == "*":
            repeat_argument = _read_group(source, index + 1)
            spec_argument = _read_group(source, repeat_argument.end) if repeat_argument else None
            if repeat_argument is None or spec_argument is None or spec_argument.end > end:
                return None
            repeat_text = source[
                repeat_argument.content_start : repeat_argument.content_end
            ].strip()
            if _MULTICOLUMN_COUNT_RE.fullmatch(repeat_text) is None:
                return None
            repeated = _count_columns(
                source,
                spec_argument.content_start,
                spec_argument.content_end,
                depth=depth + 1,
            )
            repeat = int(repeat_text)
            if repeated is None or repeat * repeated > MAX_LATEX_ROW_CELLS - count:
                return None
            count += repeat * repeated
            index = spec_argument.end
            continue
        if character in {"@", "!", ">", "<"}:
            argument = _read_group(source, index + 1)
            if argument is None or argument.end > end:
                return None
            index = argument.end
            continue
        return None
    return count if 0 < count <= MAX_LATEX_ROW_CELLS else None


def _parse_rows(
    text: str,
    source: str,
    body_start: int,
    body_end: int,
    expected_columns: int | None,
    candidate_index: _CandidateIndex,
    location_for: _LocationFactory,
) -> _RowsResult:
    raw_rows: list[_RawRow] = []
    diagnostics: list[InputDiagnostic] = []
    pending_markers: list[LatexTableStructureMarker] = []
    row_markers: list[LatexTableStructureMarker] = []
    marker_ranges: list[tuple[int, int]] = []
    cell_spans: list[tuple[int, int]] = []
    nested_environments: list[str] = []
    math_stack: list[str] = []
    brace_depth = 0
    row_start = body_start
    cell_start = body_start
    row_has_separator = False
    degraded = False
    stopped_by_limit = False
    index = body_start

    def finish_row(row_end: int, terminator_end: int) -> bool:
        nonlocal row_start, cell_start, row_has_separator, row_markers, marker_ranges
        nonlocal cell_spans, pending_markers, stopped_by_limit
        spans = (*cell_spans, (cell_start, row_end))
        has_content = _range_has_content(source, row_start, row_end, tuple(marker_ranges))
        if row_has_separator or has_content:
            if len(raw_rows) >= MAX_LATEX_TABLE_ROWS:
                diagnostics.append(
                    _input_diagnostic(
                        code="MPE_LATEX_TABLE_ROW_LIMIT",
                        severity=Severity.ERROR,
                        message=f"A table exceeds {MAX_LATEX_TABLE_ROWS} rows.",
                        location=location_for(row_start, terminator_end),
                        remediation="split the table into smaller structures",
                    )
                )
                stopped_by_limit = True
                return False
            if len(spans) > MAX_LATEX_ROW_CELLS:
                diagnostics.append(
                    _input_diagnostic(
                        code="MPE_LATEX_ROW_CELL_LIMIT",
                        severity=Severity.ERROR,
                        message=f"A row exceeds {MAX_LATEX_ROW_CELLS} physical cells.",
                        location=location_for(row_start, terminator_end),
                        remediation="split the row or reduce generated columns",
                    )
                )
                stopped_by_limit = True
                return False
            raw_rows.append(
                _RawRow(
                    start=row_start,
                    end=terminator_end,
                    cells=tuple(spans),
                    markers=tuple(
                        sorted((*pending_markers, *row_markers), key=structure_marker_sort_key)
                    ),
                    marker_ranges=tuple(marker_ranges),
                )
            )
            pending_markers = []
        else:
            pending_markers.extend(row_markers)
        row_start = terminator_end
        cell_start = terminator_end
        row_has_separator = False
        row_markers = []
        marker_ranges = []
        cell_spans = []
        return True

    while index < body_end and not stopped_by_limit:
        character = source[index]
        if character == "\\":
            command, command_end = _read_command(source, index)
            if command in {"begin", "end"}:
                argument = _read_group(source, command_end)
                if argument is not None and argument.end <= body_end:
                    environment = source[argument.content_start : argument.content_end].strip()
                    if command == "begin":
                        nested_environments.append(environment)
                    elif environment in nested_environments:
                        position = (
                            len(nested_environments)
                            - 1
                            - nested_environments[::-1].index(environment)
                        )
                        del nested_environments[position:]
                    index = argument.end
                    continue
            if command in {"(", "["} and not nested_environments:
                math_stack.append(command)
                index = command_end
                continue
            if command in {")", "]"} and not nested_environments:
                opener = "(" if command == ")" else "["
                if math_stack and math_stack[-1] == opener:
                    math_stack.pop()
                index = command_end
                continue
            at_top = not nested_environments and not math_stack and brace_depth == 0
            if at_top and command in {"\\", "tabularnewline"}:
                terminator_end = command_end
                optional = _read_group(source, terminator_end, "[", "]")
                if optional is not None and optional.end <= body_end:
                    terminator_end = optional.end
                if not finish_row(index, terminator_end):
                    break
                index = terminator_end
                continue
            if at_top and command in _STRUCTURE_COMMANDS:
                marker_end, valid = _structure_command_end(source, command, command_end, body_end)
                marker = LatexTableStructureMarker(
                    kind=_STRUCTURE_COMMANDS[command],
                    raw_latex=text[index:marker_end],
                    location=location_for(index, marker_end),
                )
                row_markers.append(marker)
                marker_ranges.append((index, marker_end))
                if not valid:
                    diagnostics.append(
                        _limitation_diagnostic(
                            code="MPW_LATEX_STRUCTURE_COMMAND_INVALID",
                            message=f"\\{command} has an invalid or unclosed argument.",
                            location=marker.location,
                            remediation="close the structure command argument",
                            details=(f"command={command}",),
                        )
                    )
                    degraded = True
                index = marker_end
                continue
            if at_top and command == "cr":
                diagnostics.append(
                    _limitation_diagnostic(
                        code="MPW_LATEX_ROW_SEPARATOR_UNSUPPORTED",
                        message="\\cr is not a supported Stage 4B1 row separator.",
                        location=location_for(index, command_end),
                        remediation="use \\\\ or \\tabularnewline",
                    )
                )
                degraded = True
            index = command_end
            continue
        if nested_environments:
            index += 1
            continue
        if character == "$" and not _is_escaped(source, index):
            marker = "$$" if source.startswith("$$", index) else "$"
            if math_stack and math_stack[-1] == marker:
                math_stack.pop()
            else:
                math_stack.append(marker)
            index += len(marker)
            continue
        if math_stack:
            index += 1
            continue
        if character == "{" and not _is_escaped(source, index):
            brace_depth += 1
            index += 1
            continue
        if character == "}" and not _is_escaped(source, index):
            brace_depth = max(0, brace_depth - 1)
            index += 1
            continue
        if character == "&" and brace_depth == 0 and not _is_escaped(source, index):
            cell_spans.append((cell_start, index))
            row_has_separator = True
            cell_start = index + 1
            index += 1
            continue
        index += 1

    if not stopped_by_limit:
        finish_row(body_end, body_end)
    if brace_depth or math_stack or nested_environments:
        diagnostics.append(
            _limitation_diagnostic(
                code="MPW_LATEX_UNCLOSED_CELL_CONTEXT",
                message="An unclosed group, math span, or environment degraded rows.",
                location=location_for(max(body_start, cell_start), body_end),
                remediation="close the group, math span, or nested environment",
            )
        )
        degraded = True

    rows: list[LatexTableRow] = []
    total_cells = 0
    for raw_row in raw_rows:
        if total_cells + len(raw_row.cells) > MAX_LATEX_TABLE_CELLS:
            diagnostics.append(
                _input_diagnostic(
                    code="MPE_LATEX_TABLE_CELL_LIMIT",
                    severity=Severity.ERROR,
                    message=f"A table exceeds {MAX_LATEX_TABLE_CELLS} total cells.",
                    location=location_for(raw_row.start, raw_row.end),
                    remediation="split the table into smaller structures",
                )
            )
            stopped_by_limit = True
            break
        logical_start = 0
        cells: list[LatexTableCell] = []
        row_degraded = False
        for physical_index, (start, end) in enumerate(raw_row.cells):
            cell, cell_diagnostics, cell_stopped = _build_cell(
                text,
                source,
                start,
                end,
                physical_index,
                logical_start,
                raw_row.marker_ranges,
                candidate_index,
                location_for,
            )
            diagnostics.extend(cell_diagnostics)
            if cell_stopped or cell is None:
                stopped_by_limit = True
                break
            cells.append(cell)
            logical_start += cell.logical_column_span
            row_degraded = row_degraded or (cell.reliability is LatexTableReliability.DEGRADED)
        if stopped_by_limit:
            break
        total_cells += len(cells)
        if expected_columns is not None and logical_start != expected_columns:
            diagnostics.append(
                _input_diagnostic(
                    code="MPW_LATEX_COLUMN_COUNT_MISMATCH",
                    severity=Severity.WARNING,
                    message=(
                        f"Row has {logical_start} logical columns; "
                        f"the specification declares {expected_columns}."
                    ),
                    location=location_for(raw_row.start, raw_row.end),
                    remediation="review separators and multicolumn spans",
                    observed=logical_start,
                    expected=expected_columns,
                )
            )
            row_degraded = True
        rows.append(
            LatexTableRow(
                row_index=len(rows),
                location=location_for(raw_row.start, raw_row.end),
                cells=tuple(cells),
                logical_column_count=logical_start,
                structure_markers=raw_row.markers,
                reliability=(
                    LatexTableReliability.DEGRADED if row_degraded else LatexTableReliability.PARSED
                ),
            )
        )
        degraded = degraded or row_degraded
    return _RowsResult(
        rows=tuple(rows),
        trailing_markers=tuple(sorted(pending_markers, key=structure_marker_sort_key)),
        diagnostics=tuple(sorted(diagnostics, key=diagnostic_sort_key)),
        degraded=degraded or stopped_by_limit,
        stopped_by_limit=stopped_by_limit,
    )


def _build_cell(
    text: str,
    source: str,
    start: int,
    end: int,
    physical_index: int,
    logical_start: int,
    ignored_ranges: tuple[tuple[int, int], ...],
    candidate_index: _CandidateIndex,
    location_for: _LocationFactory,
) -> tuple[LatexTableCell | None, tuple[InputDiagnostic, ...], bool]:
    if end - start > MAX_LATEX_CELL_CHARS:
        diagnostic = _input_diagnostic(
            code="MPE_LATEX_CELL_TOO_LONG",
            severity=Severity.ERROR,
            message=f"A cell exceeds {MAX_LATEX_CELL_CHARS} characters.",
            location=location_for(start, end),
            remediation="shorten or split the cell content",
        )
        return None, (diagnostic,), True
    shape = _parse_multicolumn_shape(text, source, start, end, ignored_ranges, location_for)
    diagnostics = list(shape.diagnostics)
    limitations = list(shape.limitations)
    formatting, formatting_diagnostics = _scan_formatting(
        source, shape.content_start, shape.content_end, location_for
    )
    diagnostics.extend(formatting_diagnostics)
    if formatting_diagnostics:
        limitations.append("MPW_LATEX_FORMATTING_INVALID")
    if _contains_command(source, shape.content_start, shape.content_end, "multirow"):
        multirow = _limitation_diagnostic(
            code="MPW_LATEX_MULTIROW_UNSUPPORTED",
            message="multirow is recognized but cross-row structure is not expanded.",
            location=location_for(shape.content_start, shape.content_end),
            remediation="review this table manually or remove multirow",
        )
        diagnostics.append(multirow)
        limitations.append(multirow.code)

    references: list[LatexCellNumericReference] = []
    for candidate in candidate_index.within(shape.content_start, shape.content_end):
        candidate_start = cast(int, candidate.location.char_start)
        primary_end = candidate_start + len(candidate.value.raw_text)
        kinds = tuple(
            sorted(
                {
                    item.kind
                    for item in formatting
                    if cast(int, item.content_location.char_start) <= candidate_start
                    and primary_end <= cast(int, item.content_location.char_end)
                },
                key=str,
            )
        )
        references.append(LatexCellNumericReference(candidate=candidate, formatting=kinds))
    normalized = _normalize_text(source, shape.content_start, shape.content_end, ignored_ranges)
    reliability = (
        LatexTableReliability.DEGRADED
        if limitations or diagnostics
        else LatexTableReliability.PARSED
    )
    return (
        LatexTableCell(
            physical_index=physical_index,
            logical_column_start=logical_start,
            logical_column_span=shape.logical_span,
            multicolumn_format=shape.multicolumn_format,
            location=location_for(start, end),
            content_location=location_for(shape.content_start, shape.content_end),
            raw_latex=text[start:end],
            normalized_text=normalized,
            is_empty=not normalized.strip(),
            numeric_references=tuple(
                sorted(references, key=lambda item: candidate_sort_key(item.candidate))
            ),
            formatting=tuple(sorted(formatting, key=formatting_sort_key)),
            reliability=reliability,
            limitations=tuple(sorted(set(limitations))),
        ),
        tuple(sorted(diagnostics, key=diagnostic_sort_key)),
        shape.stopped_by_limit,
    )


def _parse_multicolumn_shape(
    text: str,
    source: str,
    start: int,
    end: int,
    ignored_ranges: tuple[tuple[int, int], ...],
    location_for: _LocationFactory,
) -> _CellShape:
    visible_start = _skip_ignored_whitespace(source, start, end, ignored_ranges)
    command, command_end = _read_command(source, visible_start)
    if visible_start >= end or command != "multicolumn":
        return _CellShape(start, end, 1, None, (), ())
    count_argument = _read_group(source, command_end)
    format_argument = _read_group(source, count_argument.end) if count_argument else None
    content_argument = _read_group(source, format_argument.end) if format_argument else None
    if (
        count_argument is None
        or format_argument is None
        or content_argument is None
        or content_argument.end > end
        or _range_has_content(source, content_argument.end, end, ignored_ranges)
    ):
        diagnostic = _limitation_diagnostic(
            code="MPW_LATEX_MULTICOLUMN_INVALID",
            message="multicolumn is missing closed literal arguments or has trailing content.",
            location=location_for(visible_start, min(end, command_end)),
            remediation="use \\multicolumn{N}{FORMAT}{CONTENT} as the complete cell",
        )
        return _CellShape(start, end, 1, None, (diagnostic.code,), (diagnostic,))
    raw_count = text[count_argument.content_start : count_argument.content_end].strip()
    if _MULTICOLUMN_COUNT_RE.fullmatch(raw_count) is None:
        diagnostic = _limitation_diagnostic(
            code="MPW_LATEX_MULTICOLUMN_SPAN_INVALID",
            message="multicolumn span must be a literal positive integer.",
            location=location_for(count_argument.content_start, count_argument.content_end),
            remediation="replace the span with a positive integer literal",
            details=(f"span={raw_count}",),
        )
        return _CellShape(start, end, 1, None, (diagnostic.code,), (diagnostic,))
    span = int(raw_count)
    if span > MAX_LATEX_MULTICOLUMN_SPAN:
        diagnostic = _input_diagnostic(
            code="MPE_LATEX_MULTICOLUMN_SPAN_LIMIT",
            severity=Severity.ERROR,
            message=f"multicolumn span exceeds {MAX_LATEX_MULTICOLUMN_SPAN}.",
            location=location_for(count_argument.content_start, count_argument.content_end),
            remediation="reduce the literal multicolumn span",
            observed=span,
            expected=MAX_LATEX_MULTICOLUMN_SPAN,
        )
        return _CellShape(
            start,
            end,
            1,
            None,
            (diagnostic.code,),
            (diagnostic,),
            stopped_by_limit=True,
        )
    return _CellShape(
        content_start=content_argument.content_start,
        content_end=content_argument.content_end,
        logical_span=span,
        multicolumn_format=text[format_argument.content_start : format_argument.content_end],
        limitations=(),
        diagnostics=(),
    )


def _scan_formatting(
    source: str,
    start: int,
    end: int,
    location_for: _LocationFactory,
) -> tuple[tuple[LatexCellFormatting, ...], tuple[InputDiagnostic, ...]]:
    formatting: list[LatexCellFormatting] = []
    diagnostics: list[InputDiagnostic] = []
    index = start
    while index < end:
        if source[index] != "\\":
            index += 1
            continue
        command, command_end = _read_command(source, index)
        kind = _FORMATTING_COMMANDS.get(command or "")
        if kind is None:
            index = command_end
            continue
        argument = _read_group(source, command_end)
        if argument is None or argument.end > end:
            diagnostics.append(
                _limitation_diagnostic(
                    code="MPW_LATEX_FORMATTING_INVALID",
                    message=f"\\{command} is missing a closed braced argument.",
                    location=location_for(index, command_end),
                    remediation=f"close the \\{command} argument",
                    details=(f"command={command}",),
                )
            )
            index = command_end
            continue
        formatting.append(
            LatexCellFormatting(
                kind=kind,
                location=location_for(index, argument.end),
                content_location=location_for(argument.content_start, argument.content_end),
            )
        )
        index = command_end
    return (
        tuple(sorted(formatting, key=formatting_sort_key)),
        tuple(sorted(diagnostics, key=diagnostic_sort_key)),
    )


def _contains_command(source: str, start: int, end: int, expected: str) -> bool:
    index = start
    while index < end:
        if source[index] != "\\":
            index += 1
            continue
        command, command_end = _read_command(source, index)
        if command == expected:
            return True
        index = command_end
    return False


def _structure_command_end(
    source: str,
    command: str,
    command_end: int,
    body_end: int,
) -> tuple[int, bool]:
    index = command_end
    if command == "cmidrule":
        index = _skip_whitespace(source, index)
        if index < body_end and source[index] == "(":
            closing = source.find(")", index + 1, body_end)
            if closing < 0:
                return command_end, False
            index = closing + 1
    if command in {"cline", "cmidrule"}:
        argument = _read_group(source, index)
        if argument is None:
            return command_end, False
        return argument.end, argument.end <= body_end
    if command == "addlinespace":
        optional = _read_group(source, index, "[", "]")
        if optional is not None and optional.end <= body_end:
            return optional.end, True
    return command_end, True


def _normalize_text(
    source: str,
    start: int,
    end: int,
    ignored_ranges: tuple[tuple[int, int], ...] = (),
) -> str:
    pieces: list[str] = []
    index = start
    while index < end:
        ignored_end = _ignored_range_end(index, ignored_ranges)
        if ignored_end is not None:
            index = ignored_end
            continue
        character = source[index]
        if character == "\\":
            command, command_end = _read_command(source, index)
            if command in _FORMATTING_COMMANDS:
                argument = _read_group(source, command_end)
                if argument is not None and argument.end <= end:
                    pieces.append(
                        _normalize_text(
                            source,
                            argument.content_start,
                            argument.content_end,
                            ignored_ranges,
                        )
                    )
                    index = argument.end
                    continue
            if command in _ESCAPED_TEXT_SYMBOLS:
                pieces.append(command)
            elif command is not None:
                pieces.append(f"\\{command} ")
            index = command_end
            continue
        if character not in {"{", "}"}:
            pieces.append(character)
        index += 1
    return " ".join("".join(pieces).split())


def _range_has_content(
    source: str,
    start: int,
    end: int,
    ignored_ranges: tuple[tuple[int, int], ...],
) -> bool:
    return bool(_normalize_text(source, start, end, ignored_ranges).strip())


def _skip_ignored_whitespace(
    source: str,
    start: int,
    end: int,
    ignored_ranges: tuple[tuple[int, int], ...],
) -> int:
    index = start
    while index < end:
        ignored_end = _ignored_range_end(index, ignored_ranges)
        if ignored_end is not None:
            index = ignored_end
            continue
        if not source[index].isspace():
            break
        index += 1
    return index


def _ignored_range_end(
    index: int,
    ignored_ranges: tuple[tuple[int, int], ...],
) -> int | None:
    return next((end for start, end in ignored_ranges if start <= index < end), None)


def _diagnostics_for_span(
    diagnostics: tuple[InputDiagnostic, ...],
    span: _EnvironmentSpan,
) -> tuple[InputDiagnostic, ...]:
    return tuple(
        item
        for item in diagnostics
        if item.location.char_start is not None
        and span.start <= item.location.char_start <= span.end
    )


def _read_command(source: str, start: int) -> tuple[str | None, int]:
    if start >= len(source) or source[start] != "\\" or start + 1 >= len(source):
        return None, min(len(source), start + 1)
    index = start + 1
    if source[index].isalpha() or source[index] == "@":
        index += 1
        while index < len(source) and (source[index].isalpha() or source[index] == "@"):
            index += 1
        return source[start + 1 : index], index
    return source[index], index + 1


def _read_group(
    source: str,
    start: int,
    opener: str = "{",
    closer: str = "}",
) -> _Argument | None:
    index = _skip_whitespace(source, start)
    if index >= len(source) or source[index] != opener:
        return None
    depth = 1
    cursor = index + 1
    while cursor < len(source):
        character = source[cursor]
        if character == opener and not _is_escaped(source, cursor):
            depth += 1
        elif character == closer and not _is_escaped(source, cursor):
            depth -= 1
            if depth == 0:
                return _Argument(index, index + 1, cursor, cursor + 1)
        cursor += 1
    return None


def _skip_whitespace(source: str, start: int) -> int:
    index = start
    while index < len(source) and source[index].isspace():
        index += 1
    return index


def _is_escaped(source: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and source[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _input_diagnostic(
    *,
    code: str,
    severity: Severity,
    message: str,
    location: SourceLocation,
    remediation: str,
    details: tuple[str, ...] = (),
    observed: str | int | bool | None = None,
    expected: str | int | bool | None = None,
) -> InputDiagnostic:
    return make_input_diagnostic(
        code=code,
        severity=severity,
        message=message,
        location=location,
        remediation=remediation,
        evidence_details=details,
        observed=observed,
        expected=expected,
    )


def _limitation_diagnostic(
    *,
    code: str,
    message: str,
    location: SourceLocation,
    remediation: str,
    details: tuple[str, ...] = (),
) -> InputDiagnostic:
    return replace(
        _input_diagnostic(
            code=code,
            severity=Severity.WARNING,
            message=message,
            location=location,
            remediation=remediation,
            details=details,
        ),
        kind=DiagnosticKind.LIMITATION,
    )
