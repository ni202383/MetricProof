"""Format-independent results from controlled LaTeX source scanning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from metricproof.domain.models import (
    InputDiagnostic,
    NumericValue,
    SourceLocation,
    diagnostic_sort_key,
)


class LatexSyntacticContext(StrEnum):
    """Small, deliberately non-semantic LaTeX context categories."""

    TEXT = "text"
    MATH = "math"
    COMMAND_ARGUMENT = "command_argument"
    TABLE_ENVIRONMENT = "table_environment"
    CAPTION = "caption"
    UNKNOWN = "unknown"


class NumericCandidateKind(StrEnum):
    """Raw lexical relationship represented by a candidate."""

    VALUE = "value"
    MEAN_STD = "mean_std"


@dataclass(frozen=True, slots=True)
class RawNumericCandidate:
    """A source number that has not been classified as an experimental Claim."""

    kind: NumericCandidateKind
    raw_text: str
    value: NumericValue
    location: SourceLocation
    context: LatexSyntacticContext
    environments: tuple[str, ...]
    entry_paths: tuple[str, ...]
    include_chain: tuple[str, ...]
    prefix: str = ""
    suffix: str = ""
    command: str | None = None
    uncertainty: NumericValue | None = None

    def __post_init__(self) -> None:
        if not self.raw_text:
            raise ValueError("candidate raw_text must not be empty")
        if tuple(sorted(set(self.entry_paths))) != self.entry_paths or not self.entry_paths:
            raise ValueError("entry_paths must be non-empty, unique, and sorted")
        if not self.include_chain:
            raise ValueError("include_chain must not be empty")
        if self.include_chain[-1] != self.location.path:
            raise ValueError("include_chain must end at the defining file")
        if self.kind is NumericCandidateKind.MEAN_STD and self.uncertainty is None:
            raise ValueError("mean_std candidates require an uncertainty")
        if self.kind is NumericCandidateKind.VALUE and self.uncertainty is not None:
            raise ValueError("value candidates must not carry an uncertainty")


@dataclass(frozen=True, slots=True, order=True)
class LatexSourceDocument:
    """One unique physical LaTeX source inside the project boundary."""

    path: str
    byte_count: int
    char_count: int

    def __post_init__(self) -> None:
        if self.byte_count < 0 or self.char_count < 0:
            raise ValueError("document sizes must be non-negative")


@dataclass(frozen=True, slots=True)
class LatexIncludeEdge:
    """One successfully resolved static input/include dependency."""

    source_path: str
    target_path: str
    command: str
    location: SourceLocation

    def __post_init__(self) -> None:
        if self.command not in {"input", "include"}:
            raise ValueError("include edge command must be input or include")


@dataclass(frozen=True, slots=True)
class LatexSourceGraph:
    """Stable source graph summary without filesystem or parser objects."""

    entry_paths: tuple[str, ...]
    documents: tuple[LatexSourceDocument, ...]
    edges: tuple[LatexIncludeEdge, ...]

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.entry_paths))) != self.entry_paths:
            raise ValueError("entry_paths must be unique and sorted")
        if tuple(sorted(self.documents, key=lambda item: item.path)) != self.documents:
            raise ValueError("documents must be sorted by path")
        if tuple(sorted(self.edges, key=include_edge_sort_key)) != self.edges:
            raise ValueError("include edges must use stable ordering")


class LatexTableKind(StrEnum):
    """Supported containers/structures and explicitly recognized unsupported forms."""

    TABLE = "table"
    TABLE_STAR = "table*"
    TABULAR = "tabular"
    TABULAR_STAR = "tabular*"
    LONGTABLE = "longtable"
    TABULARX = "tabularx"
    ARRAY = "array"
    MATRIX = "matrix"
    ALIGNED = "aligned"


class LatexTableReliability(StrEnum):
    """How safely later stages may consume a parsed table structure."""

    PARSED = "parsed"
    DEGRADED = "degraded"
    UNSUPPORTED = "unsupported"


class LatexFormattingKind(StrEnum):
    """Source formatting recognized without executing TeX."""

    BOLD = "bold"
    UNDERLINE = "underline"


class LatexTableStructureKind(StrEnum):
    """Recognized row-boundary structure commands."""

    HLINE = "hline"
    CLINE = "cline"
    TOPRULE = "toprule"
    MIDRULE = "midrule"
    BOTTOMRULE = "bottomrule"
    CMIDRULE = "cmidrule"
    ADDLINESPACE = "addlinespace"


@dataclass(frozen=True, slots=True)
class LatexTableText:
    """Controlled caption or label content with exact source provenance."""

    raw_text: str
    normalized_text: str
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class LatexColumnSpec:
    """Raw tabular column specification and an optional reliable count."""

    raw_latex: str
    location: SourceLocation
    expected_column_count: int | None

    def __post_init__(self) -> None:
        if not self.raw_latex:
            raise ValueError("column specification raw_latex must not be empty")
        if self.expected_column_count is not None and self.expected_column_count < 1:
            raise ValueError("expected column count must be positive when available")


@dataclass(frozen=True, slots=True)
class LatexCellFormatting:
    """One exact supported formatting command and its content range."""

    kind: LatexFormattingKind
    location: SourceLocation
    content_location: SourceLocation

    def __post_init__(self) -> None:
        if self.location.path != self.content_location.path:
            raise ValueError("formatting ranges must use one source file")


@dataclass(frozen=True, slots=True)
class LatexCellNumericReference:
    """Reference to an existing raw candidate plus formatting on its primary value."""

    candidate: RawNumericCandidate
    formatting: tuple[LatexFormattingKind, ...] = ()

    def __post_init__(self) -> None:
        if tuple(sorted(set(self.formatting), key=str)) != self.formatting:
            raise ValueError("numeric reference formatting must be unique and sorted")


@dataclass(frozen=True, slots=True)
class LatexTableStructureMarker:
    """One non-data command retained near a table row boundary."""

    kind: LatexTableStructureKind
    raw_latex: str
    location: SourceLocation

    def __post_init__(self) -> None:
        if not self.raw_latex:
            raise ValueError("structure marker raw_latex must not be empty")


@dataclass(frozen=True, slots=True)
class LatexTableCell:
    """One physical cell and its logical-column structure facts."""

    physical_index: int
    logical_column_start: int
    logical_column_span: int
    multicolumn_format: str | None
    location: SourceLocation
    content_location: SourceLocation
    raw_latex: str
    normalized_text: str
    is_empty: bool
    numeric_references: tuple[LatexCellNumericReference, ...]
    formatting: tuple[LatexCellFormatting, ...]
    reliability: LatexTableReliability
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.physical_index < 0 or self.logical_column_start < 0:
            raise ValueError("cell indexes must be non-negative")
        if self.logical_column_span < 1:
            raise ValueError("logical column span must be positive")
        if self.location.path != self.content_location.path:
            raise ValueError("cell and content ranges must use one source file")
        if self.is_empty != (not self.normalized_text.strip()):
            raise ValueError("cell is_empty must match normalized_text")
        if tuple(sorted(self.numeric_references, key=numeric_reference_sort_key)) != (
            self.numeric_references
        ):
            raise ValueError("numeric references must use stable source ordering")
        if tuple(sorted(self.formatting, key=formatting_sort_key)) != self.formatting:
            raise ValueError("cell formatting must use stable source ordering")
        if tuple(sorted(set(self.limitations))) != self.limitations:
            raise ValueError("cell limitations must be unique and sorted")


@dataclass(frozen=True, slots=True)
class LatexTableRow:
    """One source row with physical cells and a validated logical width."""

    row_index: int
    location: SourceLocation
    cells: tuple[LatexTableCell, ...]
    logical_column_count: int
    structure_markers: tuple[LatexTableStructureMarker, ...]
    reliability: LatexTableReliability

    def __post_init__(self) -> None:
        if self.row_index < 0 or self.logical_column_count < 0:
            raise ValueError("row indexes and logical column counts must be non-negative")
        if tuple(cell.physical_index for cell in self.cells) != tuple(range(len(self.cells))):
            raise ValueError("physical cell indexes must be contiguous from zero")
        if sum(cell.logical_column_span for cell in self.cells) != self.logical_column_count:
            raise ValueError("row logical column count must equal cell spans")
        if tuple(sorted(self.structure_markers, key=structure_marker_sort_key)) != (
            self.structure_markers
        ):
            raise ValueError("row structure markers must use stable source ordering")


@dataclass(frozen=True, slots=True)
class LatexTable:
    """One supported tabular or explicitly recognized unsupported table environment."""

    environment: LatexTableKind
    location: SourceLocation
    container_environment: LatexTableKind | None
    container_location: SourceLocation | None
    caption: LatexTableText | None
    label: LatexTableText | None
    column_spec: LatexColumnSpec | None
    rows: tuple[LatexTableRow, ...]
    structure_markers: tuple[LatexTableStructureMarker, ...]
    diagnostics: tuple[InputDiagnostic, ...]
    reliability: LatexTableReliability

    def __post_init__(self) -> None:
        supported = {LatexTableKind.TABULAR, LatexTableKind.TABULAR_STAR}
        containers = {LatexTableKind.TABLE, LatexTableKind.TABLE_STAR}
        if self.environment in supported and self.reliability is LatexTableReliability.UNSUPPORTED:
            raise ValueError("supported tabular environments cannot be marked unsupported")
        if (
            self.environment not in supported
            and self.reliability is not LatexTableReliability.UNSUPPORTED
        ):
            raise ValueError("unsupported environments must be marked unsupported")
        if (self.container_environment is None) != (self.container_location is None):
            raise ValueError("container environment and location must be present together")
        if self.container_environment is not None and self.container_environment not in containers:
            raise ValueError("table container must be table or table*")
        if tuple(row.row_index for row in self.rows) != tuple(range(len(self.rows))):
            raise ValueError("table row indexes must be contiguous from zero")
        if tuple(sorted(self.structure_markers, key=structure_marker_sort_key)) != (
            self.structure_markers
        ):
            raise ValueError("table structure markers must use stable source ordering")
        if tuple(sorted(self.diagnostics, key=diagnostic_sort_key)) != self.diagnostics:
            raise ValueError("table diagnostics must use stable ordering")

    @property
    def expected_column_count(self) -> int | None:
        return None if self.column_spec is None else self.column_spec.expected_column_count


@dataclass(frozen=True, slots=True)
class PaperScanStatistics:
    """Bounded counts describing the actual scan work and output."""

    scanned_file_count: int
    total_bytes: int
    candidate_count: int
    diagnostic_count: int
    table_count: int = 0
    parsed_table_count: int = 0
    degraded_table_count: int = 0
    unsupported_table_count: int = 0

    def __post_init__(self) -> None:
        if (
            min(
                self.scanned_file_count,
                self.total_bytes,
                self.candidate_count,
                self.diagnostic_count,
                self.table_count,
                self.parsed_table_count,
                self.degraded_table_count,
                self.unsupported_table_count,
            )
            < 0
        ):
            raise ValueError("scan statistics must be non-negative")
        classified = (
            self.parsed_table_count + self.degraded_table_count + self.unsupported_table_count
        )
        if classified != self.table_count:
            raise ValueError("table reliability counts must equal table_count")


@dataclass(frozen=True, slots=True)
class PaperScanResult:
    """Raw candidate scan result; explicitly not a PaperClaim collection."""

    graph: LatexSourceGraph
    candidates: tuple[RawNumericCandidate, ...]
    diagnostics: tuple[InputDiagnostic, ...]
    statistics: PaperScanStatistics
    complete: bool
    tables: tuple[LatexTable, ...] = ()

    def __post_init__(self) -> None:
        if tuple(sorted(self.tables, key=table_sort_key)) != self.tables:
            raise ValueError("tables must use stable source ordering")

    @property
    def has_blocking_errors(self) -> bool:
        return any(diagnostic.blocking for diagnostic in self.diagnostics)


def candidate_sort_key(candidate: RawNumericCandidate) -> tuple[str, int, int, str]:
    """Stable source order for raw numeric candidates."""

    return (
        candidate.location.path,
        candidate.location.char_start if candidate.location.char_start is not None else -1,
        candidate.location.char_end if candidate.location.char_end is not None else -1,
        candidate.raw_text,
    )


def include_edge_sort_key(edge: LatexIncludeEdge) -> tuple[str, int, str, str]:
    """Stable source order for resolved include edges."""

    return (
        edge.source_path,
        edge.location.char_start if edge.location.char_start is not None else -1,
        edge.target_path,
        edge.command,
    )


def formatting_sort_key(formatting: LatexCellFormatting) -> tuple[str, int, str]:
    return (
        formatting.location.path,
        formatting.location.char_start if formatting.location.char_start is not None else -1,
        formatting.kind.value,
    )


def numeric_reference_sort_key(
    reference: LatexCellNumericReference,
) -> tuple[str, int, int, str]:
    return candidate_sort_key(reference.candidate)


def structure_marker_sort_key(
    marker: LatexTableStructureMarker,
) -> tuple[str, int, str]:
    return (
        marker.location.path,
        marker.location.char_start if marker.location.char_start is not None else -1,
        marker.kind.value,
    )


def table_sort_key(table: LatexTable) -> tuple[str, int, str]:
    return (
        table.location.path,
        table.location.char_start if table.location.char_start is not None else -1,
        table.environment.value,
    )
