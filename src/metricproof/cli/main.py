"""Typer composition root and user-facing output for MetricProof."""

from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from rich.console import Console
from rich.table import Table

from metricproof import __version__
from metricproof.adapters.config import YamlConfigurationRepository, find_project_root
from metricproof.adapters.doctor import LocalDoctorProbe
from metricproof.adapters.experiments import LocalExperimentSourceReader
from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.doctor import DoctorProbe, DoctorReport, run_doctor
from metricproof.application.errors import ExitCode, MetricProofError
from metricproof.application.experiments import load_experiments
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.application.ports import ConfigurationRepository, ExperimentSourceReader
from metricproof.domain.models import ExperimentCatalog, InputDiagnostic, ScalarValue

app = typer.Typer(
    name="metricproof",
    help="Local-first consistency checks for experimental claims.",
    add_completion=False,
    no_args_is_help=True,
    pretty_exceptions_enable=False,
)
experiments_app = typer.Typer(
    name="experiments",
    help="Read and validate declared local experiment result files.",
    no_args_is_help=True,
)
app.add_typer(experiments_app, name="experiments")


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


@experiments_app.command("list")
def list_experiments(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit stable machine-readable JSON."),
    ] = False,
) -> None:
    """List normalized experiment runs and metrics."""

    _run_experiments_command(command="list", json_output=json_output)


@experiments_app.command("validate")
def validate_experiments(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit stable machine-readable JSON."),
    ] = False,
) -> None:
    """Validate config.yml and every declared experiment source."""

    _run_experiments_command(command="validate", json_output=json_output)


def _run_experiments_command(*, command: str, json_output: bool) -> None:
    try:
        project_root, configuration, catalog = _load_catalog()
    except KeyboardInterrupt:
        _render_command_error(
            command,
            json_output,
            code="MP_INTERRUPTED",
            message="Operation interrupted by the user.",
            exit_code=ExitCode.INTERRUPTED,
        )
    except ProjectConfigurationError as error:
        _render_command_error(
            command,
            json_output,
            code="MPC_CONFIG",
            message=error.message,
            exit_code=error.exit_code,
            location=error.file,
            field=error.field,
            remediation=error.remediation,
        )
    except MetricProofError as error:
        _render_command_error(
            command,
            json_output,
            code="MP_ERROR",
            message=error.message,
            exit_code=error.exit_code,
        )
    except Exception:
        _render_command_error(
            command,
            json_output,
            code="MP_INTERNAL",
            message="An unexpected internal error prevented experiment loading.",
            exit_code=ExitCode.INTERNAL_ERROR,
        )

    if json_output:
        payload = (
            _list_payload(project_root, configuration, catalog)
            if command == "list"
            else _validation_payload(project_root, configuration, catalog)
        )
        typer.echo(_json_dump(payload))
    elif command == "list":
        _render_experiment_list(catalog)
        _render_input_diagnostics(catalog.diagnostics)
    else:
        _render_validation_summary(catalog)
        _render_input_diagnostics(catalog.diagnostics)

    if catalog.has_blocking_errors:
        raise typer.Exit(code=ExitCode.INPUT_ERROR)


def _load_catalog() -> tuple[Path, ProjectConfiguration, ExperimentCatalog]:
    current = Path.cwd()
    project_root = find_project_root(current) or current.resolve()
    configuration = _build_configuration_repository().load(project_root)
    catalog = load_experiments(project_root, configuration, _build_experiment_reader())
    return project_root, configuration, catalog


def _build_doctor_probe() -> DoctorProbe:
    return LocalDoctorProbe()


def _build_configuration_repository() -> ConfigurationRepository:
    return YamlConfigurationRepository()


def _build_experiment_reader() -> ExperimentSourceReader:
    return LocalExperimentSourceReader()


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


def _render_experiment_list(catalog: ExperimentCatalog) -> None:
    if not catalog.runs:
        typer.echo("No experiments were loaded.")
        return
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=160)
    table = Table(title="MetricProof experiments", show_lines=True)
    table.add_column("Run")
    table.add_column("Metric")
    table.add_column("Value", justify="right")
    table.add_column("Source")
    table.add_column("Selector")
    for run in catalog.runs:
        for observation in run.observations:
            table.add_row(
                run.run_id,
                observation.metric_name,
                str(observation.value),
                observation.source_file,
                observation.source_selector,
            )
    console.print(table)


def _render_validation_summary(catalog: ExperimentCatalog) -> None:
    status = "failed" if catalog.has_blocking_errors else "passed"
    typer.echo(
        f"Experiment validation {status}: {len(catalog.runs)} run(s), "
        f"{len(catalog.observations)} observation(s), "
        f"{len(catalog.diagnostics)} diagnostic(s)."
    )


def _render_input_diagnostics(diagnostics: tuple[InputDiagnostic, ...]) -> None:
    if not diagnostics:
        return
    console = Console(file=sys.stderr, color_system=None, force_terminal=False, width=160)
    table = Table(title="Experiment diagnostics", show_lines=True)
    table.add_column("Severity")
    table.add_column("Code")
    table.add_column("Location")
    table.add_column("Message")
    table.add_column("Suggested fix")
    for diagnostic in diagnostics:
        table.add_row(
            diagnostic.severity.value,
            diagnostic.code,
            diagnostic.location.display,
            diagnostic.message,
            diagnostic.remediation,
        )
    console.print(table)


def _render_command_error(
    command: str,
    json_output: bool,
    *,
    code: str,
    message: str,
    exit_code: ExitCode,
    location: str | None = None,
    field: str | None = None,
    remediation: str | None = None,
) -> NoReturn:
    if json_output:
        error = {
            "code": code,
            "message": message,
            "location": location,
            "field": field,
            "remediation": remediation,
        }
        typer.echo(
            _json_dump(
                {
                    "schema_version": "1",
                    "command": f"experiments {command}",
                    "ok": False,
                    "error": error,
                }
            )
        )
    else:
        typer.echo(f"{code}: {message}", err=True)
    raise typer.Exit(code=exit_code)


def _list_payload(
    project_root: Path,
    configuration: ProjectConfiguration,
    catalog: ExperimentCatalog,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "command": "experiments list",
        "ok": not catalog.has_blocking_errors,
        "project": project_root.name,
        "config_schema_version": configuration.schema_version,
        "runs": [
            {
                "run_id": run.run_id,
                "sources": list(run.result_sources),
                "config_reference": run.config_reference,
                "metadata": {key: _json_scalar(value) for key, value in run.metadata},
                "metrics": [
                    {
                        "metric_name": observation.metric_name,
                        "value": str(observation.value),
                        "raw_value": observation.raw_value,
                        "source_file": observation.source_file,
                        "source_selector": observation.source_selector,
                        "dataset": observation.dataset,
                        "split": observation.split,
                        "seed": observation.seed,
                        "commit": observation.commit,
                    }
                    for observation in run.observations
                ],
            }
            for run in catalog.runs
        ],
        "diagnostics": [_diagnostic_payload(item) for item in catalog.diagnostics],
    }


def _validation_payload(
    project_root: Path,
    configuration: ProjectConfiguration,
    catalog: ExperimentCatalog,
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "command": "experiments validate",
        "ok": not catalog.has_blocking_errors,
        "project": project_root.name,
        "config_schema_version": configuration.schema_version,
        "summary": {
            "run_count": len(catalog.runs),
            "observation_count": len(catalog.observations),
            "diagnostic_count": len(catalog.diagnostics),
        },
        "diagnostics": [_diagnostic_payload(item) for item in catalog.diagnostics],
    }


def _diagnostic_payload(diagnostic: InputDiagnostic) -> dict[str, object]:
    return {
        "diagnostic_id": diagnostic.diagnostic_id,
        "kind": diagnostic.kind.value,
        "code": diagnostic.code,
        "severity": diagnostic.severity.value,
        "message": diagnostic.message,
        "location": {
            "path": diagnostic.location.path,
            "selector": diagnostic.location.selector,
            "line": diagnostic.location.line,
            "column": diagnostic.location.column,
        },
        "observed": _json_scalar(diagnostic.observed),
        "expected": _json_scalar(diagnostic.expected),
        "confidence": str(diagnostic.confidence),
        "remediation": diagnostic.remediation,
        "evidence": [
            {
                "evidence_id": evidence.evidence_id,
                "kind": evidence.kind,
                "summary": evidence.summary,
                "details": list(evidence.details),
            }
            for evidence in diagnostic.evidence
        ],
    }


def _json_scalar(value: ScalarValue) -> str | int | bool | None:
    return str(value) if isinstance(value, Decimal) else value


def _json_dump(payload: dict[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
