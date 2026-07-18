"""Terminal and JSON rendering of the unified CheckResult only."""

from __future__ import annotations

import sys
from decimal import Decimal

import typer
from rich.console import Console
from rich.table import Table

from metricproof.domain.diagnostics import CheckDiagnostic, CheckResult
from metricproof.domain.models import Evidence, ScalarValue, SourceLocation


def check_result_payload(result: CheckResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "command": "check",
        "tool_version": result.tool_version,
        "project": result.project,
        "summary": {
            "checked_claim_count": result.summary.checked_claim_count,
            "registry": dict(result.summary.registry_counts),
            "migrations": dict(result.summary.migration_counts),
            "diagnostics_by_code": dict(result.summary.diagnostic_counts),
            "diagnostics_by_severity": dict(result.summary.severity_counts),
            "diagnostic_count": len(result.diagnostics),
        },
        "diagnostics": [_diagnostic_payload(item) for item in result.diagnostics],
    }


def render_check_result(result: CheckResult) -> None:
    registry = dict(result.summary.registry_counts)
    typer.echo(
        f"MetricProof check: {result.summary.checked_claim_count} current Claim(s), "
        f"{registry.get('active', 0)} active, "
        f"{registry.get('ignored', 0)} ignored, "
        f"{registry.get('broken', 0)} broken, "
        f"{registry.get('unlinked', 0)} unlinked, "
        f"{registry.get('ambiguous', 0)} ambiguous, "
        f"{registry.get('missing', 0)} missing; "
        f"{len(result.diagnostics)} diagnostic(s)."
    )
    if not result.diagnostics:
        typer.echo("No diagnostics were produced by the selected checks.")
        return
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=200)
    table = Table(title="MetricProof CheckResult diagnostics", show_lines=True)
    table.add_column("Severity")
    table.add_column("Code")
    table.add_column("Claim ID")
    table.add_column("Location")
    table.add_column("Observed")
    table.add_column("Expected")
    table.add_column("Message")
    table.add_column("Evidence")
    table.add_column("Suggested action")
    for diagnostic in result.diagnostics:
        table.add_row(
            diagnostic.severity.value,
            diagnostic.code,
            diagnostic.claim_id or "",
            diagnostic.location.display,
            _display_scalar(diagnostic.observed),
            _display_scalar(diagnostic.expected),
            diagnostic.message,
            "; ".join(item.summary for item in diagnostic.evidence),
            diagnostic.remediation,
        )
    console.print(table)


def _diagnostic_payload(diagnostic: CheckDiagnostic) -> dict[str, object]:
    return {
        "diagnostic_id": diagnostic.diagnostic_id,
        "kind": diagnostic.kind.value,
        "code": diagnostic.code,
        "severity": diagnostic.severity.value,
        "message": diagnostic.message,
        "claim_id": diagnostic.claim_id,
        "location": _location_payload(diagnostic.location),
        "observed": _json_scalar(diagnostic.observed),
        "expected": _json_scalar(diagnostic.expected),
        "confidence": str(diagnostic.confidence),
        "evidence": [_evidence_payload(item) for item in diagnostic.evidence],
        "related_sources": [_location_payload(location) for location in diagnostic.related_sources],
        "remediation": diagnostic.remediation,
        "uncertainties": list(diagnostic.uncertainties),
    }


def _evidence_payload(evidence: Evidence) -> dict[str, object]:
    return {
        "evidence_id": evidence.evidence_id,
        "kind": evidence.kind,
        "summary": evidence.summary,
        "location": _location_payload(evidence.location) if evidence.location else None,
        "details": list(evidence.details),
    }


def _location_payload(location: SourceLocation) -> dict[str, object]:
    return {
        "path": location.path,
        "selector": location.selector,
        "line": location.line,
        "column": location.column,
        "end_line": location.end_line,
        "end_column": location.end_column,
        "char_start": location.char_start,
        "char_end": location.char_end,
        "display": location.display,
    }


def _json_scalar(value: ScalarValue) -> ScalarValue:
    return str(value) if isinstance(value, Decimal) else value


def _display_scalar(value: ScalarValue) -> str:
    return "" if value is None else str(value)
