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
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.doctor import DoctorProbe, DoctorReport, run_doctor
from metricproof.application.errors import ExitCode, MetricProofError
from metricproof.application.experiments import load_experiments
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.application.paper import scan_paper
from metricproof.application.ports import (
    ConfigurationRepository,
    ExperimentSourceReader,
    PaperScanner,
)
from metricproof.domain.models import ExperimentCatalog, InputDiagnostic, ScalarValue
from metricproof.domain.paper import (
    LatexSyntacticContext,
    PaperScanResult,
    RawNumericCandidate,
)

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


@app.command()
def scan(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit stable machine-readable JSON."),
    ] = False,
    show_all: Annotated[
        bool,
        typer.Option(
            "--show-all",
            help="Also show low-context command-argument and unknown candidates.",
        ),
    ] = False,
    file_path: Annotated[
        str | None,
        typer.Option(
            "--file",
            help="Show candidates from one .tex file already in the configured graph.",
        ),
    ] = None,
) -> None:
    """Scan configured LaTeX sources for raw numeric candidates."""

    try:
        project_root, configuration, result = _load_paper_scan(file_path)
    except KeyboardInterrupt:
        _render_scan_error(
            json_output,
            code="MP_INTERRUPTED",
            message="Operation interrupted by the user.",
            exit_code=ExitCode.INTERRUPTED,
        )
    except ProjectConfigurationError as error:
        _render_scan_error(
            json_output,
            code="MPC_CONFIG",
            message=error.message,
            exit_code=error.exit_code,
            location=error.file,
            field=error.field,
            remediation=error.remediation,
        )
    except MetricProofError as error:
        _render_scan_error(
            json_output,
            code="MP_ERROR",
            message=error.message,
            exit_code=error.exit_code,
        )
    except Exception:
        _render_scan_error(
            json_output,
            code="MP_INTERNAL",
            message="An unexpected internal error prevented LaTeX scanning.",
            exit_code=ExitCode.INTERNAL_ERROR,
        )

    displayed = _displayed_candidates(result, show_all=show_all)
    if json_output:
        typer.echo(_json_dump(_scan_payload(project_root, configuration, result, displayed)))
    else:
        _render_scan_result(result, displayed)
        _render_input_diagnostics(result.diagnostics, title="LaTeX scan diagnostics")
    if result.has_blocking_errors:
        raise typer.Exit(code=ExitCode.INPUT_ERROR)


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


def _load_paper_scan(
    selected_file: str | None,
) -> tuple[Path, ProjectConfiguration, PaperScanResult]:
    current = Path.cwd()
    project_root = find_project_root(current) or current.resolve()
    configuration = _build_configuration_repository().load(project_root)
    result = scan_paper(
        project_root,
        configuration,
        _build_paper_scanner(),
        selected_file=selected_file,
    )
    return project_root, configuration, result


def _build_doctor_probe() -> DoctorProbe:
    return LocalDoctorProbe()


def _build_configuration_repository() -> ConfigurationRepository:
    return YamlConfigurationRepository()


def _build_experiment_reader() -> ExperimentSourceReader:
    return LocalExperimentSourceReader()


def _build_paper_scanner() -> PaperScanner:
    return LocalLatexPaperScanner()


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


def _render_input_diagnostics(
    diagnostics: tuple[InputDiagnostic, ...],
    *,
    title: str = "Experiment diagnostics",
) -> None:
    if not diagnostics:
        return
    console = Console(file=sys.stderr, color_system=None, force_terminal=False, width=160)
    table = Table(title=title, show_lines=True)
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


def _render_scan_error(
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
        typer.echo(
            _json_dump(
                {
                    "schema_version": "1",
                    "command": "scan",
                    "result_type": "raw_numeric_candidates",
                    "ok": False,
                    "error": {
                        "code": code,
                        "message": message,
                        "location": location,
                        "field": field,
                        "remediation": remediation,
                    },
                }
            )
        )
    else:
        typer.echo(f"{code}: {message}", err=True)
    raise typer.Exit(code=exit_code)


def _displayed_candidates(
    result: PaperScanResult,
    *,
    show_all: bool,
) -> tuple[RawNumericCandidate, ...]:
    if show_all:
        return result.candidates
    low_context = {
        LatexSyntacticContext.COMMAND_ARGUMENT,
        LatexSyntacticContext.UNKNOWN,
    }
    return tuple(item for item in result.candidates if item.context not in low_context)


def _render_scan_result(
    result: PaperScanResult,
    displayed: tuple[RawNumericCandidate, ...],
) -> None:
    typer.echo(
        f"LaTeX raw numeric scan: {result.statistics.scanned_file_count} file(s), "
        f"{result.statistics.candidate_count} raw candidate(s), "
        f"{len(displayed)} displayed, "
        f"{result.statistics.diagnostic_count} diagnostic(s), "
        f"complete={str(result.complete).lower()}."
    )
    if not displayed:
        typer.echo("No raw numeric candidates matched the current display filter.")
        return
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=180)
    table = Table(title="MetricProof raw numeric candidates", show_lines=True)
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Column", justify="right")
    table.add_column("Raw")
    table.add_column("Canonical")
    table.add_column("Context")
    table.add_column("Command")
    for candidate in displayed:
        table.add_row(
            candidate.location.path,
            str(candidate.location.line or ""),
            str(candidate.location.column or ""),
            candidate.raw_text,
            _candidate_canonical(candidate),
            candidate.context.value,
            candidate.command or "",
        )
    console.print(table)


def _candidate_canonical(candidate: RawNumericCandidate) -> str:
    mean = str(candidate.value.canonical)
    if candidate.uncertainty is None:
        return mean
    return f"{mean} +/- {candidate.uncertainty.canonical}"


def _scan_payload(
    project_root: Path,
    configuration: ProjectConfiguration,
    result: PaperScanResult,
    displayed: tuple[RawNumericCandidate, ...],
) -> dict[str, object]:
    return {
        "schema_version": "1",
        "command": "scan",
        "result_type": "raw_numeric_candidates",
        "ok": not result.has_blocking_errors,
        "complete": result.complete,
        "project": project_root.name,
        "config_schema_version": configuration.schema_version,
        "summary": {
            "scanned_file_count": result.statistics.scanned_file_count,
            "total_bytes": result.statistics.total_bytes,
            "raw_candidate_count": result.statistics.candidate_count,
            "displayed_candidate_count": len(displayed),
            "diagnostic_count": result.statistics.diagnostic_count,
        },
        "graph": {
            "entry_paths": list(result.graph.entry_paths),
            "documents": [
                {
                    "path": document.path,
                    "byte_count": document.byte_count,
                    "char_count": document.char_count,
                }
                for document in result.graph.documents
            ],
            "edges": [
                {
                    "source_path": edge.source_path,
                    "target_path": edge.target_path,
                    "command": edge.command,
                    "location": _location_payload(edge.location),
                }
                for edge in result.graph.edges
            ],
        },
        "candidates": [_candidate_payload(candidate) for candidate in displayed],
        "diagnostics": [_diagnostic_payload(item) for item in result.diagnostics],
    }


def _candidate_payload(candidate: RawNumericCandidate) -> dict[str, object]:
    return {
        "candidate_kind": candidate.kind.value,
        "raw_text": candidate.raw_text,
        "value": _numeric_payload(candidate.value),
        "uncertainty": (
            _numeric_payload(candidate.uncertainty) if candidate.uncertainty is not None else None
        ),
        "location": _location_payload(candidate.location),
        "syntactic_context": candidate.context.value,
        "environments": list(candidate.environments),
        "command": candidate.command,
        "prefix": candidate.prefix,
        "suffix": candidate.suffix,
        "entry_paths": list(candidate.entry_paths),
        "include_chain": list(candidate.include_chain),
    }


def _numeric_payload(value: object) -> dict[str, object]:
    from metricproof.domain.models import NumericValue

    if not isinstance(value, NumericValue):
        raise TypeError("scan numeric payload requires NumericValue")
    return {
        "raw_text": value.raw_text,
        "parsed": str(value.parsed),
        "canonical": str(value.canonical),
        "unit": value.unit.value,
        "kind": value.kind.value,
        "decimal_places": value.decimal_places,
        "scale": str(value.scale),
        "sign": value.sign,
    }


def _location_payload(location: object) -> dict[str, object]:
    from metricproof.domain.models import SourceLocation

    if not isinstance(location, SourceLocation):
        raise TypeError("scan location payload requires SourceLocation")
    return {
        "path": location.path,
        "selector": location.selector,
        "line": location.line,
        "column": location.column,
        "end_line": location.end_line,
        "end_column": location.end_column,
        "char_start": location.char_start,
        "char_end": location.char_end,
    }


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
            "end_line": diagnostic.location.end_line,
            "end_column": diagnostic.location.end_column,
            "char_start": diagnostic.location.char_start,
            "char_end": diagnostic.location.char_end,
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
