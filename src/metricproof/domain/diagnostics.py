"""Unified, stable diagnostics and CheckResult consumed by every check renderer."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from hashlib import sha256

from metricproof.domain.models import Evidence, ScalarValue, Severity, SourceLocation

CHECK_RESULT_SCHEMA_VERSION = "1"


class CheckDiagnosticKind(StrEnum):
    RULE = "rule"
    INPUT = "input"
    LINK = "link"
    LIMITATION = "limitation"
    INTERNAL = "internal"


@dataclass(frozen=True, slots=True)
class CheckDiagnostic:
    """One locatable, cautious rule/input/link finding."""

    diagnostic_id: str
    kind: CheckDiagnosticKind
    code: str
    severity: Severity
    message: str
    location: SourceLocation
    evidence: tuple[Evidence, ...]
    confidence: Decimal
    remediation: str
    claim_id: str | None = None
    observed: ScalarValue = None
    expected: ScalarValue = None
    related_sources: tuple[SourceLocation, ...] = ()
    uncertainties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.diagnostic_id.startswith("diag_"):
            raise ValueError("check diagnostic IDs must start with diag_")
        if not self.code.strip() or not self.message.strip() or not self.remediation.strip():
            raise ValueError("check diagnostics require code, message, and remediation")
        if not Decimal("0") <= self.confidence <= Decimal("1"):
            raise ValueError("diagnostic confidence must be between 0 and 1")
        if tuple(sorted(set(self.related_sources))) != self.related_sources:
            raise ValueError("related diagnostic sources must be unique and sorted")
        if tuple(sorted(set(self.uncertainties))) != self.uncertainties:
            raise ValueError("diagnostic uncertainties must be unique and sorted")


@dataclass(frozen=True, slots=True)
class CheckSummary:
    checked_claim_count: int
    registry_counts: tuple[tuple[str, int], ...]
    migration_counts: tuple[tuple[str, int], ...]
    diagnostic_counts: tuple[tuple[str, int], ...]
    severity_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if self.checked_claim_count < 0:
            raise ValueError("checked Claim count must be non-negative")
        for values in (
            self.registry_counts,
            self.migration_counts,
            self.diagnostic_counts,
            self.severity_counts,
        ):
            if tuple(sorted(values)) != values:
                raise ValueError("CheckResult summary mappings must use stable key ordering")
            if len({key for key, _ in values}) != len(values):
                raise ValueError("CheckResult summary mappings require unique keys")
            if any(count < 0 for _, count in values):
                raise ValueError("CheckResult summary counts must be non-negative")


@dataclass(frozen=True, slots=True)
class CheckResult:
    """The sole facts rendered by terminal and JSON check outputs."""

    schema_version: str
    tool_version: str
    project: str
    summary: CheckSummary
    diagnostics: tuple[CheckDiagnostic, ...]

    def __post_init__(self) -> None:
        if self.schema_version != CHECK_RESULT_SCHEMA_VERSION:
            raise ValueError(f"unsupported CheckResult schema: {self.schema_version!r}")
        if not self.tool_version.strip() or not self.project.strip():
            raise ValueError("CheckResult requires tool version and project display name")
        if tuple(sorted(self.diagnostics, key=check_diagnostic_sort_key)) != self.diagnostics:
            raise ValueError("CheckResult diagnostics must use stable ordering")

    @property
    def has_blocking_input_errors(self) -> bool:
        return any(
            item.severity is Severity.ERROR
            and item.kind in {CheckDiagnosticKind.INPUT, CheckDiagnosticKind.LINK}
            for item in self.diagnostics
        )

    def has_rule_at_or_above(self, threshold: Severity) -> bool:
        order = {Severity.INFO: 0, Severity.WARNING: 1, Severity.ERROR: 2}
        return any(
            item.kind is CheckDiagnosticKind.RULE and order[item.severity] >= order[threshold]
            for item in self.diagnostics
        )


def make_check_diagnostic(
    *,
    kind: CheckDiagnosticKind,
    code: str,
    severity: Severity,
    message: str,
    location: SourceLocation,
    evidence: tuple[Evidence, ...],
    confidence: Decimal,
    remediation: str,
    claim_id: str | None = None,
    observed: ScalarValue = None,
    expected: ScalarValue = None,
    related_sources: tuple[SourceLocation, ...] = (),
    uncertainties: tuple[str, ...] = (),
) -> CheckDiagnostic:
    """Build a deterministic diagnostic identity from reviewable facts."""

    identity = "\0".join(
        (
            kind.value,
            code,
            claim_id or "",
            location.display,
            repr(observed),
            repr(expected),
            *(item.evidence_id for item in evidence),
        )
    )
    return CheckDiagnostic(
        diagnostic_id=f"diag_{sha256(identity.encode('utf-8')).hexdigest()[:20]}",
        kind=kind,
        code=code,
        severity=severity,
        message=message,
        location=location,
        evidence=evidence,
        confidence=confidence,
        remediation=remediation,
        claim_id=claim_id,
        observed=observed,
        expected=expected,
        related_sources=tuple(sorted(set(related_sources))),
        uncertainties=tuple(sorted(set(uncertainties))),
    )


def make_check_evidence(
    *,
    kind: str,
    summary: str,
    location: SourceLocation | None = None,
    details: tuple[str, ...] = (),
) -> Evidence:
    identity = "\0".join(
        (
            kind,
            summary,
            location.display if location is not None else "",
            *details,
        )
    )
    return Evidence(
        evidence_id=f"ev_{sha256(identity.encode('utf-8')).hexdigest()[:20]}",
        kind=kind,
        summary=summary,
        location=location,
        details=details,
    )


def check_diagnostic_sort_key(
    diagnostic: CheckDiagnostic,
) -> tuple[int, str, str, str, str]:
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    return (
        severity_order[diagnostic.severity],
        diagnostic.code,
        diagnostic.location.display,
        diagnostic.claim_id or "",
        diagnostic.diagnostic_id,
    )
