"""Format-independent experimental facts and input diagnostics."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath

type ScalarValue = str | int | bool | Decimal | None


class Severity(StrEnum):
    """User-visible diagnostic severity."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class DiagnosticKind(StrEnum):
    """Current diagnostic categories used by experiment loading."""

    INPUT = "input"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True, order=True)
class SourceLocation:
    """A project-relative, user-locatable data position."""

    path: str
    selector: str = ""
    line: int | None = None
    column: int | None = None
    end_line: int | None = None
    end_column: int | None = None
    char_start: int | None = None
    char_end: int | None = None

    def __post_init__(self) -> None:
        project_path = PurePosixPath(self.path)
        if not self.path or project_path.is_absolute() or ".." in project_path.parts:
            raise ValueError("source paths must be non-empty project-relative POSIX paths")
        if self.line is not None and self.line < 1:
            raise ValueError("line must be at least 1")
        if self.column is not None and self.column < 1:
            raise ValueError("column must be at least 1")
        if self.end_line is not None and self.end_line < (self.line or 1):
            raise ValueError("end_line must not precede line")
        if self.end_column is not None and self.end_column < 1:
            raise ValueError("end_column must be at least 1")
        if self.char_start is not None and self.char_start < 0:
            raise ValueError("char_start must be non-negative")
        if self.char_end is not None and self.char_end <= (self.char_start or 0):
            raise ValueError("char_end must be greater than char_start")

    @property
    def display(self) -> str:
        """Return a stable compact location for human and JSON output."""

        parts = [self.path]
        if self.selector:
            parts.append(self.selector)
        if self.line is not None:
            parts.append(f"line={self.line}")
        if self.column is not None:
            parts.append(f"column={self.column}")
        return ":".join(parts)


@dataclass(frozen=True, slots=True)
class NumericValue:
    """An exact finite decimal and its original lexical representation."""

    raw_text: str
    parsed: Decimal

    def __post_init__(self) -> None:
        if not self.raw_text.strip():
            raise ValueError("numeric raw text must not be empty")
        if not self.parsed.is_finite():
            raise ValueError("numeric values must be finite")


@dataclass(frozen=True, slots=True)
class Evidence:
    """A stable description of an observed input fact."""

    evidence_id: str
    kind: str
    summary: str
    location: SourceLocation | None = None
    details: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class InputDiagnostic:
    """A structured, locatable parsing or data-integrity diagnostic."""

    diagnostic_id: str
    code: str
    severity: Severity
    message: str
    location: SourceLocation
    evidence: tuple[Evidence, ...]
    remediation: str
    observed: ScalarValue = None
    expected: ScalarValue = None
    confidence: Decimal = Decimal("1")
    kind: DiagnosticKind = DiagnosticKind.INPUT

    @property
    def blocking(self) -> bool:
        return self.severity is Severity.ERROR


@dataclass(frozen=True, slots=True)
class MetricObservation:
    """One exact metric value from a declared experiment source."""

    observation_id: str
    run_id: str
    metric_name: str
    value: Decimal
    raw_value: str
    source_file: str
    source_selector: str
    location: SourceLocation
    dataset: str | None = None
    split: str | None = None
    seed: str | int | None = None
    commit: str | None = None
    config_reference: str | None = None
    metadata: tuple[tuple[str, ScalarValue], ...] = ()

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if not self.metric_name.strip():
            raise ValueError("metric_name must not be empty")
        if not self.value.is_finite():
            raise ValueError("metric values must be finite")
        if tuple(sorted(self.metadata)) != self.metadata:
            raise ValueError("metadata must be sorted by key")

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        metric_name: str,
        numeric: NumericValue,
        source_file: str,
        source_selector: str,
        location: SourceLocation,
        dataset: str | None = None,
        split: str | None = None,
        seed: str | int | None = None,
        commit: str | None = None,
        config_reference: str | None = None,
        metadata: tuple[tuple[str, ScalarValue], ...] = (),
    ) -> MetricObservation:
        identity = "\0".join((source_file, source_selector, run_id, metric_name))
        observation_id = f"obs_{sha256(identity.encode('utf-8')).hexdigest()[:20]}"
        return cls(
            observation_id=observation_id,
            run_id=run_id,
            metric_name=metric_name,
            value=numeric.parsed,
            raw_value=numeric.raw_text,
            source_file=source_file,
            source_selector=source_selector,
            location=location,
            dataset=dataset,
            split=split,
            seed=seed,
            commit=commit,
            config_reference=config_reference,
            metadata=metadata,
        )


@dataclass(frozen=True, slots=True)
class ExperimentRun:
    """A stable experiment run assembled from one or more result sources."""

    run_id: str
    observations: tuple[MetricObservation, ...]
    metadata: tuple[tuple[str, ScalarValue], ...]
    result_sources: tuple[str, ...]
    config_reference: str | None = None
    declared_commit: str | None = None

    def __post_init__(self) -> None:
        if not self.run_id.strip():
            raise ValueError("run_id must not be empty")
        if tuple(sorted(self.observations, key=observation_sort_key)) != self.observations:
            raise ValueError("observations must use stable ordering")
        if tuple(sorted(self.metadata)) != self.metadata:
            raise ValueError("metadata must be sorted by key")
        if tuple(sorted(set(self.result_sources))) != self.result_sources:
            raise ValueError("result_sources must be unique and sorted")


@dataclass(frozen=True, slots=True)
class ExperimentCatalog:
    """Normalized runs, observations, and all recoverable input diagnostics."""

    runs: tuple[ExperimentRun, ...]
    observations: tuple[MetricObservation, ...]
    diagnostics: tuple[InputDiagnostic, ...]

    @property
    def has_blocking_errors(self) -> bool:
        return any(diagnostic.blocking for diagnostic in self.diagnostics)


def observation_sort_key(observation: MetricObservation) -> tuple[str, str, str, str]:
    return (
        observation.run_id,
        observation.metric_name,
        observation.source_file,
        observation.source_selector,
    )


def diagnostic_sort_key(diagnostic: InputDiagnostic) -> tuple[int, str, str, str]:
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    return (
        severity_order[diagnostic.severity],
        diagnostic.code,
        diagnostic.location.display,
        diagnostic.diagnostic_id,
    )


def make_input_diagnostic(
    *,
    code: str,
    severity: Severity,
    message: str,
    location: SourceLocation,
    remediation: str,
    evidence_details: tuple[str, ...] = (),
    observed: ScalarValue = None,
    expected: ScalarValue = None,
) -> InputDiagnostic:
    """Build deterministic evidence and diagnostic identities."""

    evidence_seed = "\0".join((code, location.display, *evidence_details))
    evidence_id = f"ev_{sha256(evidence_seed.encode('utf-8')).hexdigest()[:20]}"
    evidence = Evidence(
        evidence_id=evidence_id,
        kind="input",
        summary=message,
        location=location,
        details=evidence_details,
    )
    diagnostic_seed = "\0".join((code, location.display, message, evidence_id))
    diagnostic_id = f"diag_{sha256(diagnostic_seed.encode('utf-8')).hexdigest()[:20]}"
    return InputDiagnostic(
        diagnostic_id=diagnostic_id,
        code=code,
        severity=severity,
        message=message,
        location=location,
        evidence=(evidence,),
        remediation=remediation,
        observed=observed,
        expected=expected,
    )
