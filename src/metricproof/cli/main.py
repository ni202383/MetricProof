"""Typer composition root and user-facing output for MetricProof."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from metricproof import __version__
from metricproof.adapters.doctor import LocalDoctorProbe
from metricproof.application.doctor import DoctorProbe, DoctorReport, run_doctor
from metricproof.application.errors import ExitCode, MetricProofError

app = typer.Typer(
    name="metricproof",
    help="Local-first consistency checks for experimental claims.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"MetricProof {__version__}")
        raise typer.Exit(code=ExitCode.SUCCESS)


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the MetricProof version and exit.",
        ),
    ] = False,
) -> None:
    """Start the MetricProof command-line interface."""


@app.command()
def doctor() -> None:
    """Run bounded, read-only checks of the local environment."""

    try:
        report = run_doctor(_build_doctor_probe(), Path.cwd())
    except KeyboardInterrupt:
        typer.echo("MP_INTERRUPTED: operation interrupted by the user.", err=True)
        raise typer.Exit(code=ExitCode.INTERRUPTED) from None
    except MetricProofError as error:
        typer.echo(f"MP_ERROR: {error.message}", err=True)
        raise typer.Exit(code=error.exit_code) from None
    except Exception:
        typer.echo(
            "MP_INTERNAL: an unexpected internal error prevented doctor from completing.",
            err=True,
        )
        raise typer.Exit(code=ExitCode.INTERNAL_ERROR) from None

    _render_doctor_report(report)
    if report.exit_code is not ExitCode.SUCCESS:
        raise typer.Exit(code=report.exit_code)


def _build_doctor_probe() -> DoctorProbe:
    return LocalDoctorProbe()


def _render_doctor_report(report: DoctorReport) -> None:
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=140)
    table = Table(title="MetricProof doctor", show_lines=True)
    table.add_column("Status", no_wrap=True)
    table.add_column("Code", no_wrap=True)
    table.add_column("Check")
    table.add_column("Location")
    table.add_column("Evidence")
    for check in report.checks:
        table.add_row(
            check.status.value,
            check.code,
            check.message,
            check.location,
            "; ".join(check.evidence),
        )
    console.print(table)
