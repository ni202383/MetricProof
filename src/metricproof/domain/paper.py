"""Format-independent results from controlled LaTeX source scanning."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from metricproof.domain.models import InputDiagnostic, NumericValue, SourceLocation


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


@dataclass(frozen=True, slots=True)
class PaperScanStatistics:
    """Bounded counts describing the actual scan work and output."""

    scanned_file_count: int
    total_bytes: int
    candidate_count: int
    diagnostic_count: int

    def __post_init__(self) -> None:
        if (
            min(
                self.scanned_file_count,
                self.total_bytes,
                self.candidate_count,
                self.diagnostic_count,
            )
            < 0
        ):
            raise ValueError("scan statistics must be non-negative")


@dataclass(frozen=True, slots=True)
class PaperScanResult:
    """Raw candidate scan result; explicitly not a PaperClaim collection."""

    graph: LatexSourceGraph
    candidates: tuple[RawNumericCandidate, ...]
    diagnostics: tuple[InputDiagnostic, ...]
    statistics: PaperScanStatistics
    complete: bool

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
