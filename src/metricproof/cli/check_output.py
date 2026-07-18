"""Terminal and JSON rendering of the unified CheckResult only."""

from __future__ import annotations

import sys

import typer
from rich.console import Console
from rich.table import Table

from metricproof.domain.diagnostics import CheckResult
from metricproof.domain.models import ScalarValue


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
    summary_console = Console(file=sys.stdout, color_system=None, force_terminal=False)
    summary_table = Table(title="Five-rule execution summary")
    summary_table.add_column("Rule")
    summary_table.add_column("Status")
    summary_table.add_column("Errors", justify="right")
    summary_table.add_column("Warnings", justify="right")
    summary_table.add_column("Info", justify="right")
    summary_table.add_column("Limitations", justify="right")
    summary_table.add_column("Reason")
    for item in result.summary.rule_summaries:
        summary_table.add_row(
            item.code,
            item.status,
            str(item.error_count),
            str(item.warning_count),
            str(item.info_count),
            str(item.limitation_count),
            item.reason,
        )
    summary_console.print(summary_table)
    if not result.diagnostics:
        typer.echo("No diagnostics were produced by the selected checks.")
        return
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=200)
    table = Table(title="MetricProof CheckResult diagnostics", show_lines=True)
    table.add_column("Severity")
    table.add_column("Code")
    table.add_column("Subject")
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
            diagnostic.subject_id or diagnostic.claim_id or "",
            diagnostic.location.display,
            _display_scalar(diagnostic.observed),
            _display_scalar(diagnostic.expected),
            diagnostic.message,
            "; ".join(item.summary for item in diagnostic.evidence),
            diagnostic.remediation,
        )
    console.print(table)


def _display_scalar(value: ScalarValue) -> str:
    return "" if value is None else str(value)
