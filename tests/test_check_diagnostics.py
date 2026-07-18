"""Invariant and decision tests for the unified CheckResult model."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from metricproof.domain.diagnostics import (
    CHECK_RESULT_SCHEMA_VERSION,
    CheckDiagnostic,
    CheckDiagnosticKind,
    CheckResult,
    CheckSummary,
    make_check_diagnostic,
    make_check_evidence,
)
from metricproof.domain.models import Severity, SourceLocation


def _diagnostic(
    *,
    kind: CheckDiagnosticKind = CheckDiagnosticKind.RULE,
    code: str = "STALE_VALUE",
    severity: Severity = Severity.ERROR,
    path: str = "paper/main.tex",
) -> CheckDiagnostic:
    location = SourceLocation(path, line=2, column=4)
    evidence = make_check_evidence(
        kind="numeric-comparison",
        summary="paper and source values differ",
        location=location,
        details=("paper=0.8", "source=0.9"),
    )
    return make_check_diagnostic(
        kind=kind,
        code=code,
        severity=severity,
        message="The displayed value may be stale.",
        location=location,
        evidence=(evidence,),
        confidence=Decimal("0.95"),
        remediation="Review the paper value and linked metric.",
        claim_id="clm_12345678901234567890",
        observed=Decimal("0.8"),
        expected=Decimal("0.9"),
    )


def _summary() -> CheckSummary:
    return CheckSummary(
        checked_claim_count=1,
        registry_counts=(("active", 1),),
        migration_counts=(),
        diagnostic_counts=(("STALE_VALUE", 1),),
        severity_counts=(("error", 1),),
    )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"diagnostic_id": "bad"}, "start with diag_"),
        ({"code": " "}, "code, message, and remediation"),
        ({"message": ""}, "code, message, and remediation"),
        ({"remediation": ""}, "code, message, and remediation"),
        ({"confidence": Decimal("-0.01")}, "between 0 and 1"),
        ({"confidence": Decimal("1.01")}, "between 0 and 1"),
        (
            {
                "related_sources": (
                    SourceLocation("z.tex"),
                    SourceLocation("a.tex"),
                )
            },
            "sources must be unique and sorted",
        ),
        ({"uncertainties": ("rounding", "rounding")}, "uncertainties must be unique"),
    ],
)
def test_check_diagnostic_rejects_unstable_or_incomplete_facts(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_diagnostic(), **changes)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"checked_claim_count": -1}, "non-negative"),
        ({"registry_counts": (("z", 1), ("a", 1))}, "stable key ordering"),
        ({"migration_counts": (("same", 1), ("same", 2))}, "unique keys"),
        ({"severity_counts": (("error", -1),)}, "non-negative"),
    ],
)
def test_check_summary_rejects_nondeterministic_or_invalid_counts(
    changes: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_summary(), **changes)


def test_factories_are_stable_and_normalize_review_metadata() -> None:
    first = _diagnostic()
    duplicate = _diagnostic()
    source_a = SourceLocation("a.tex")
    source_z = SourceLocation("z.tex")
    normalized = make_check_diagnostic(
        kind=first.kind,
        code=first.code,
        severity=first.severity,
        message=first.message,
        location=first.location,
        evidence=first.evidence,
        confidence=first.confidence,
        remediation=first.remediation,
        claim_id=first.claim_id,
        observed=first.observed,
        expected=first.expected,
        related_sources=(source_z, source_a, source_z),
        uncertainties=("unit interpretation", "rounding", "rounding"),
    )

    assert first.diagnostic_id == duplicate.diagnostic_id
    assert first.evidence[0].evidence_id == duplicate.evidence[0].evidence_id
    assert normalized.related_sources == (source_a, source_z)
    assert normalized.uncertainties == ("rounding", "unit interpretation")
    changed_evidence = make_check_evidence(
        kind="numeric-comparison",
        summary="paper and source values differ",
        location=first.location,
        details=("paper=0.8", "source=0.91"),
    )
    assert changed_evidence.evidence_id != first.evidence[0].evidence_id


def test_check_result_validates_ordering_and_metadata() -> None:
    error = _diagnostic(code="WRONG_DELTA")
    warning = _diagnostic(
        code="MISSING_PROVENANCE",
        severity=Severity.WARNING,
    )
    ordered = (error, warning)
    result = CheckResult(
        schema_version=CHECK_RESULT_SCHEMA_VERSION,
        tool_version="0.1.0",
        project=".",
        summary=_summary(),
        diagnostics=ordered,
    )

    assert result.diagnostics == ordered
    with pytest.raises(ValueError, match="unsupported CheckResult schema"):
        replace(result, schema_version="999")
    with pytest.raises(ValueError, match="tool version and project"):
        replace(result, tool_version=" ")
    with pytest.raises(ValueError, match="tool version and project"):
        replace(result, project="")
    with pytest.raises(ValueError, match="stable ordering"):
        replace(result, diagnostics=tuple(reversed(ordered)))


def test_check_result_exit_predicates_distinguish_rule_and_input_findings() -> None:
    input_error = _diagnostic(kind=CheckDiagnosticKind.INPUT, code="INPUT_BAD")
    link_error = _diagnostic(kind=CheckDiagnosticKind.LINK, code="LINK_BAD")
    rule_warning = _diagnostic(
        kind=CheckDiagnosticKind.RULE,
        code="MISSING_PROVENANCE",
        severity=Severity.WARNING,
    )
    limitation_error = _diagnostic(
        kind=CheckDiagnosticKind.LIMITATION,
        code="LIMITATION",
    )

    def result(*diagnostics: CheckDiagnostic) -> CheckResult:
        ordered = tuple(
            sorted(
                diagnostics,
                key=lambda item: (
                    {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}[item.severity],
                    item.code,
                    item.location.display,
                    item.claim_id or "",
                    item.diagnostic_id,
                ),
            )
        )
        return CheckResult(
            schema_version=CHECK_RESULT_SCHEMA_VERSION,
            tool_version="0.1.0",
            project=".",
            summary=_summary(),
            diagnostics=ordered,
        )

    assert result(input_error).has_blocking_input_errors
    assert result(link_error).has_blocking_input_errors
    assert not result(limitation_error, rule_warning).has_blocking_input_errors
    assert result(rule_warning).has_rule_at_or_above(Severity.WARNING)
    assert not result(rule_warning).has_rule_at_or_above(Severity.ERROR)
