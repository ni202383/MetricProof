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
from metricproof.adapters.claim_registry import YamlClaimRegistryRepository
from metricproof.adapters.config import YamlConfigurationRepository, find_project_root
from metricproof.adapters.doctor import LocalDoctorProbe
from metricproof.adapters.experiment_configs import LocalExperimentConfigReader
from metricproof.adapters.experiments import LocalExperimentSourceReader
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.adapters.reports import REPORT_FORMATS, check_result_payload, write_report
from metricproof.application.checking import CORE_RULE_CODES, check_project
from metricproof.application.claim_registry import load_claim_registry, save_claim_registry
from metricproof.application.claims import classify_claim_candidates
from metricproof.application.comparisons import load_config_snapshots
from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.doctor import DoctorProbe, DoctorReport, run_doctor
from metricproof.application.errors import ExitCode, MetricProofError
from metricproof.application.experiments import load_experiments
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.application.linking import (
    LinkReviewItem,
    LinkSession,
    build_link_session,
    entry_from_candidate,
    entry_from_observation,
    ignored_entry,
)
from metricproof.application.paper import scan_paper
from metricproof.application.ports import (
    ConfigurationRepository,
    ExperimentConfigReader,
    ExperimentSourceReader,
    PaperScanner,
)
from metricproof.application.registry_ports import ClaimRegistryRepository
from metricproof.cli.check_output import render_check_result
from metricproof.cli.claim_output import classification_payloads, render_claim_classifications
from metricproof.cli.link_output import (
    link_session_payload,
    render_link_session,
    render_match_candidates,
)
from metricproof.domain.claims import ClaimClassificationResult
from metricproof.domain.diagnostics import CheckResult
from metricproof.domain.links import LinkScale
from metricproof.domain.models import (
    ExperimentCatalog,
    InputDiagnostic,
    MetricObservation,
    ScalarValue,
    Severity,
)
from metricproof.domain.paper import (
    LatexSyntacticContext,
    LatexTable,
    LatexTableCell,
    PaperScanResult,
    RawNumericCandidate,
)
from metricproof.domain.registry import ClaimRegistry, IgnoreReason

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
            help="Show every classification and all raw-candidate debug contexts.",
        ),
    ] = False,
    show_claims: Annotated[
        bool,
        typer.Option(
            "--show-claims",
            help="Show likely and possible experimental Claim classifications.",
        ),
    ] = False,
    show_tables: Annotated[
        bool,
        typer.Option(
            "--show-tables",
            help="Show parsed table, row, cell, numeric, and formatting details.",
        ),
    ] = False,
    file_path: Annotated[
        str | None,
        typer.Option(
            "--file",
            help="Show candidates and tables from one .tex graph file.",
        ),
    ] = None,
) -> None:
    """Scan LaTeX sources and heuristically classify raw numeric candidates."""

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

    classifications = classify_claim_candidates(result, configuration)
    displayed = _displayed_candidates(result, show_all=show_all)
    if json_output:
        typer.echo(
            _json_dump(
                _scan_payload(
                    project_root,
                    configuration,
                    result,
                    classifications,
                    displayed,
                )
            )
        )
    else:
        _render_scan_result(
            result,
            classifications,
            displayed,
            show_claims=show_claims,
            show_all=show_all,
            show_tables=show_tables,
        )
        _render_input_diagnostics(result.diagnostics, title="LaTeX scan diagnostics")
    if result.has_blocking_errors:
        raise typer.Exit(code=ExitCode.INPUT_ERROR)


@app.command()
def link(
    claim_id: Annotated[
        str | None,
        typer.Option("--claim", help="Review one stable Claim ID."),
    ] = None,
    non_interactive: Annotated[
        bool,
        typer.Option(
            "--non-interactive",
            help="Generate suggestions without prompting or writing claims.yml.",
        ),
    ] = False,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit stable suggestion JSON without prompting or writing claims.yml.",
        ),
    ] = False,
    show_broken: Annotated[
        bool,
        typer.Option("--show-broken", help="Include Claims with unavailable linked sources."),
    ] = False,
) -> None:
    """Review suggestions and explicitly persist Claim links or ignore decisions."""

    try:
        project_root, configuration, scan_result, catalog, session = _load_link_session()
    except KeyboardInterrupt:
        _render_link_error(
            json_output,
            code="MP_INTERRUPTED",
            message="Operation interrupted by the user; claims.yml was not changed.",
            exit_code=ExitCode.INTERRUPTED,
        )
    except ProjectConfigurationError as error:
        _render_link_error(
            json_output,
            code="MPC_CONFIG",
            message=error.message,
            exit_code=error.exit_code,
            location=error.file,
            field=error.field,
            remediation=error.remediation,
        )
    except MetricProofError as error:
        _render_link_error(
            json_output,
            code="MP_LINK_INPUT",
            message=error.message,
            exit_code=error.exit_code,
        )
    except Exception:
        _render_link_error(
            json_output,
            code="MP_INTERNAL",
            message="An unexpected internal error prevented Claim link preparation.",
            exit_code=ExitCode.INTERNAL_ERROR,
        )

    selected = session.get(claim_id) if claim_id is not None else None
    if claim_id is not None and selected is None:
        _render_link_error(
            json_output,
            code="MPL_CLAIM_NOT_FOUND",
            message=f"Claim {claim_id!r} is not present in the current or retained registry state.",
            exit_code=ExitCode.USAGE_ERROR,
            remediation="Run metricproof link --non-interactive --json to list stable Claim IDs.",
        )

    blocking = (
        scan_result.has_blocking_errors
        or catalog.has_blocking_errors
        or bool(session.identity_collisions)
    )
    if json_output:
        payload = link_session_payload(session, selected_claim=claim_id)
        payload["ok"] = not blocking
        payload["paper_diagnostics"] = [
            _diagnostic_payload(item) for item in scan_result.diagnostics
        ]
        payload["experiment_diagnostics"] = [
            _diagnostic_payload(item) for item in catalog.diagnostics
        ]
        typer.echo(_json_dump(payload))
        if blocking:
            raise typer.Exit(code=ExitCode.INPUT_ERROR)
        return

    displayed = render_link_session(
        session,
        selected_claim=claim_id,
        show_broken=show_broken,
    )
    _render_input_diagnostics(scan_result.diagnostics, title="LaTeX scan diagnostics")
    _render_input_diagnostics(catalog.diagnostics, title="Experiment diagnostics")
    for collision in session.identity_collisions:
        typer.echo(f"MPL_IDENTITY_COLLISION: {collision}", err=True)
    if blocking:
        raise typer.Exit(code=ExitCode.INPUT_ERROR)
    if non_interactive:
        for item in displayed:
            render_match_candidates(item)
        return

    try:
        updated, decision_count, cancelled = _interactive_link_review(
            displayed,
            catalog,
            session.registry,
        )
        if cancelled:
            typer.echo("Link review cancelled; claims.yml was not changed.")
            return
        if decision_count == 0:
            typer.echo("No link or ignore decisions were selected; claims.yml was not changed.")
            return
        if not typer.confirm(
            f"Write {decision_count} decision(s) to {configuration.claim_registry_path}?",
            default=True,
        ):
            typer.echo("Write cancelled; claims.yml was not changed.")
            return
        save_claim_registry(
            project_root,
            configuration.claim_registry_path,
            updated,
            _build_claim_registry_repository(),
        )
    except (KeyboardInterrupt, typer.Abort):
        _render_link_error(
            False,
            code="MP_INTERRUPTED",
            message="Operation interrupted by the user; claims.yml was not changed.",
            exit_code=ExitCode.INTERRUPTED,
        )
    except MetricProofError as error:
        _render_link_error(
            False,
            code="MP_LINK_WRITE",
            message=error.message,
            exit_code=error.exit_code,
        )
    typer.echo(
        f"Saved {decision_count} confirmed decision(s) to {configuration.claim_registry_path}."
    )


@app.command()
def check(
    json_output: Annotated[
        bool,
        typer.Option("--json", help="Emit stable machine-readable CheckResult JSON."),
    ] = False,
    rule: Annotated[
        str | None,
        typer.Option(
            "--rule",
            help="Run one of the five local consistency rules.",
        ),
    ] = None,
    fail_on: Annotated[
        str | None,
        typer.Option(
            "--fail-on",
            help="Override the rule failure threshold with warning or error.",
        ),
    ] = None,
) -> None:
    """Run five local consistency rules through one unified CheckResult."""

    selected_rules = CORE_RULE_CODES
    if rule is not None:
        normalized_rule = rule.strip().upper()
        if normalized_rule not in CORE_RULE_CODES:
            _render_check_error(
                json_output,
                code="MPC_RULE",
                message=f"Unsupported rule code: {rule!r}.",
                exit_code=ExitCode.USAGE_ERROR,
                remediation=(
                    "Use STALE_VALUE, WRONG_DELTA, MISSING_PROVENANCE, "
                    "WRONG_BEST_MARK, or UNFAIR_COMPARISON."
                ),
            )
        selected_rules = frozenset({normalized_rule})
    if fail_on is not None and fail_on.strip().casefold() not in {"warning", "error"}:
        _render_check_error(
            json_output,
            code="MPC_FAIL_ON",
            message=f"Unsupported --fail-on value: {fail_on!r}.",
            exit_code=ExitCode.USAGE_ERROR,
            remediation="Use --fail-on warning or --fail-on error.",
        )

    try:
        _, configuration, result = _load_check_result(selected_rules)
    except KeyboardInterrupt:
        _render_check_error(
            json_output,
            code="MP_INTERRUPTED",
            message="Operation interrupted by the user.",
            exit_code=ExitCode.INTERRUPTED,
        )
    except ProjectConfigurationError as error:
        _render_check_error(
            json_output,
            code="MPC_CONFIG",
            message=error.message,
            exit_code=error.exit_code,
            location=error.file,
            field=error.field,
            remediation=error.remediation,
        )
    except MetricProofError as error:
        _render_check_error(
            json_output,
            code="MP_CHECK_INPUT",
            message=error.message,
            exit_code=error.exit_code,
        )
    except Exception:
        _render_check_error(
            json_output,
            code="MP_INTERNAL",
            message="An unexpected internal error prevented project checking.",
            exit_code=ExitCode.INTERNAL_ERROR,
        )

    threshold = (
        Severity(fail_on.strip().casefold())
        if fail_on is not None
        else configuration.rule_policy.fail_on
    )
    rule_failure = result.has_rule_at_or_above(threshold)
    if json_output:
        payload = check_result_payload(result)
        payload["ok"] = not result.has_blocking_input_errors and not rule_failure
        payload["fail_on"] = threshold.value
        typer.echo(_json_dump(payload))
    else:
        render_check_result(result)
    if result.has_blocking_input_errors:
        raise typer.Exit(code=ExitCode.INPUT_ERROR)
    if rule_failure:
        raise typer.Exit(code=ExitCode.ANALYSIS_FAILURE)


@app.command()
def report(
    report_format: Annotated[
        str,
        typer.Option("--format", help="Report format: html or json."),
    ] = "html",
    output: Annotated[
        str,
        typer.Option("--output", help="Project-relative output file."),
    ] = "metricproof-report.html",
    no_timestamp: Annotated[
        bool,
        typer.Option("--no-timestamp", help="Omit generation time for byte-stable output."),
    ] = False,
) -> None:
    """Generate one offline report from the same CheckResult as metricproof check."""

    normalized_format = report_format.strip().casefold()
    if normalized_format not in REPORT_FORMATS:
        _render_check_error(
            False,
            code="MPC_REPORT_FORMAT",
            message=f"Unsupported report format: {report_format!r}.",
            exit_code=ExitCode.USAGE_ERROR,
            remediation="Use --format html or --format json.",
        )
    try:
        project_root, configuration, result = _load_check_result(CORE_RULE_CODES)
        destination = write_report(
            project_root,
            output,
            normalized_format,
            result,
            no_timestamp=no_timestamp,
        )
    except KeyboardInterrupt:
        _render_check_error(
            False,
            code="MP_INTERRUPTED",
            message="Operation interrupted by the user.",
            exit_code=ExitCode.INTERRUPTED,
        )
    except ProjectConfigurationError as error:
        _render_check_error(
            False,
            code="MPC_CONFIG",
            message=error.message,
            exit_code=error.exit_code,
            location=error.file,
            field=error.field,
            remediation=error.remediation,
        )
    except MetricProofError as error:
        _render_check_error(
            False,
            code="MP_REPORT_INPUT",
            message=error.message,
            exit_code=error.exit_code,
        )
    except ValueError as error:
        _render_check_error(
            False,
            code="MPC_REPORT_OUTPUT",
            message=str(error),
            exit_code=ExitCode.USAGE_ERROR,
            remediation="Use a project-relative output path inside the project root.",
        )
    except OSError as error:
        _render_check_error(
            False,
            code="MP_REPORT_WRITE",
            message=f"The report could not be written: {error}",
            exit_code=ExitCode.ENVIRONMENT_ERROR,
            remediation="Check the output path and local file permissions.",
        )
    relative = destination.relative_to(project_root).as_posix()
    typer.echo(f"MetricProof {normalized_format.upper()} report written to {relative}.")
    if result.has_blocking_input_errors:
        raise typer.Exit(code=ExitCode.INPUT_ERROR)
    if result.has_rule_at_or_above(configuration.rule_policy.fail_on):
        raise typer.Exit(code=ExitCode.ANALYSIS_FAILURE)


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


def _load_link_session() -> tuple[
    Path,
    ProjectConfiguration,
    PaperScanResult,
    ExperimentCatalog,
    LinkSession,
]:
    project_root, configuration, scan_result = _load_paper_scan(None)
    catalog = load_experiments(project_root, configuration, _build_experiment_reader())
    registry = load_claim_registry(
        project_root,
        configuration.claim_registry_path,
        _build_claim_registry_repository(),
    )
    session = build_link_session(scan_result, configuration, catalog, registry)
    return project_root, configuration, scan_result, catalog, session


def _load_check_result(
    selected_rules: frozenset[str],
) -> tuple[Path, ProjectConfiguration, CheckResult]:
    project_root, configuration, scan_result = _load_paper_scan(None)
    catalog = load_experiments(project_root, configuration, _build_experiment_reader())
    registry = load_claim_registry(
        project_root,
        configuration.claim_registry_path,
        _build_claim_registry_repository(),
    )
    config_snapshots, config_diagnostics = load_config_snapshots(
        project_root,
        configuration,
        catalog,
        _build_experiment_config_reader(),
    )
    result = check_project(
        scan_result,
        configuration,
        catalog,
        registry,
        tool_version=__version__,
        selected_rules=selected_rules,
        config_snapshots=config_snapshots,
        config_diagnostics=config_diagnostics,
        project_display=project_root.name,
    )
    return project_root, configuration, result


def _interactive_link_review(
    items: tuple[LinkReviewItem, ...],
    catalog: ExperimentCatalog,
    registry: ClaimRegistry,
) -> tuple[ClaimRegistry, int, bool]:
    updated = registry
    decision_count = 0
    for item in items:
        if not item.reviewable:
            typer.echo(
                f"{item.claim_id} is {item.status.value}; it cannot be rebound without "
                "an unambiguous current Claim."
            )
            continue
        if item.status.value == "active" and not typer.confirm(
            f"{item.claim_id} already has an active link. Replace it?",
            default=False,
        ):
            continue
        render_match_candidates(item)
        action = _prompt_link_action(len(item.matches.candidates) if item.matches else 0)
        if action == "q":
            return registry, 0, True
        if action == "s":
            continue
        if action == "i":
            note = typer.prompt("Ignore note", default="", show_default=False)
            if typer.confirm("Persist this Claim as ignored?", default=False):
                updated = updated.with_entry(
                    ignored_entry(item, reason=IgnoreReason.USER_DECISION, note=note)
                )
                decision_count += 1
            continue
        if action == "m":
            observation = _prompt_manual_observation(catalog)
            if observation is None:
                continue
            scale = _prompt_link_scale(LinkScale.IDENTITY)
            if typer.confirm("Confirm this manual DirectLink?", default=False):
                updated = updated.with_entry(entry_from_observation(item, observation, scale=scale))
                decision_count += 1
            continue
        candidate_index = int(action) - 1
        assert item.matches is not None
        candidate = item.matches.candidates[candidate_index]
        scale = _prompt_link_scale(candidate.suggested_scale)
        if typer.confirm(
            f"Confirm this {candidate.suggestion_type.value} link?",
            default=False,
        ):
            updated = updated.with_entry(entry_from_candidate(item, candidate, scale=scale))
            decision_count += 1
    return updated, decision_count, False


def _prompt_link_action(candidate_count: int) -> str:
    choices = {"m", "i", "s", "q", *(str(index) for index in range(1, candidate_count + 1))}
    prompt = (
        f"Choose candidate 1-{candidate_count}, [m]anual, [i]gnore, [s]kip, or [q]uit"
        if candidate_count
        else "Choose [m]anual, [i]gnore, [s]kip, or [q]uit"
    )
    while True:
        value = typer.prompt(prompt, default="s").strip().casefold()
        if value in choices:
            return value
        typer.echo("Enter a listed candidate number or m, i, s, q.", err=True)


def _prompt_link_scale(default: LinkScale) -> LinkScale:
    allowed = {item.value: item for item in LinkScale}
    while True:
        value = typer.prompt(
            "Scale (identity/fraction_to_percent/percent_to_fraction)",
            default=default.value,
        ).strip()
        if value in allowed:
            return allowed[value]
        typer.echo("Scale must be identity, fraction_to_percent, or percent_to_fraction.", err=True)


def _prompt_manual_observation(catalog: ExperimentCatalog) -> MetricObservation | None:
    if not catalog.observations:
        typer.echo("No experiment observations are available for manual selection.")
        return None
    typer.echo("Available observations:")
    for index, observation in enumerate(catalog.observations, start=1):
        typer.echo(
            f"  {index}. {observation.run_id}/{observation.metric_name}="
            f"{observation.value} ({observation.source_file}:{observation.source_selector})"
        )
    while True:
        value = typer.prompt("Observation number or s to skip", default="s").strip().casefold()
        if value == "s":
            return None
        if value.isdigit() and 1 <= int(value) <= len(catalog.observations):
            return catalog.observations[int(value) - 1]
        typer.echo("Enter a listed observation number or s.", err=True)


def _build_doctor_probe() -> DoctorProbe:
    return LocalDoctorProbe()


def _build_configuration_repository() -> ConfigurationRepository:
    return YamlConfigurationRepository()


def _build_claim_registry_repository() -> ClaimRegistryRepository:
    return YamlClaimRegistryRepository()


def _build_experiment_reader() -> ExperimentSourceReader:
    return LocalExperimentSourceReader()


def _build_experiment_config_reader() -> ExperimentConfigReader:
    return LocalExperimentConfigReader()


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


def _render_link_error(
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
                    "command": "link",
                    "ok": False,
                    "write_performed": False,
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


def _render_check_error(
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
                    "command": "check",
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
                    "schema_version": "3",
                    "command": "scan",
                    "result_type": "paper_scan",
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
    classifications: ClaimClassificationResult,
    displayed: tuple[RawNumericCandidate, ...],
    *,
    show_claims: bool,
    show_all: bool,
    show_tables: bool,
) -> None:
    typer.echo(
        f"LaTeX raw numeric scan: {result.statistics.scanned_file_count} file(s), "
        f"{result.statistics.candidate_count} raw candidate(s), "
        f"{classifications.statistics.likely_count} likely, "
        f"{classifications.statistics.possible_count} possible, "
        f"{classifications.statistics.ambiguous_count} ambiguous, "
        f"{classifications.statistics.non_experiment_count} non-experiment, "
        f"{len(displayed)} raw displayed, "
        f"{result.statistics.table_count} table(s) "
        f"({result.statistics.parsed_table_count} parsed, "
        f"{result.statistics.degraded_table_count} degraded, "
        f"{result.statistics.unsupported_table_count} unsupported), "
        f"{result.statistics.diagnostic_count} diagnostic(s), "
        f"complete={str(result.complete).lower()}."
    )
    if displayed:
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
    else:
        typer.echo("No raw numeric candidates matched the current display filter.")
    if show_claims or show_all:
        render_claim_classifications(classifications, show_all=show_all)
    if show_tables:
        _render_table_details(result.tables)


def _render_table_details(tables: tuple[LatexTable, ...]) -> None:
    if not tables:
        typer.echo("No LaTeX tables were found.")
        return
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=200)
    overview = Table(title="MetricProof LaTeX tables", show_lines=True)
    overview.add_column("#", justify="right")
    overview.add_column("File")
    overview.add_column("Environment")
    overview.add_column("Caption / label")
    overview.add_column("Rows", justify="right")
    overview.add_column("Expected", justify="right")
    overview.add_column("Reliability")
    overview.add_column("Reasons")
    for table_index, table in enumerate(tables, start=1):
        metadata = " / ".join(
            item
            for item in (
                table.caption.normalized_text if table.caption else "",
                table.label.normalized_text if table.label else "",
            )
            if item
        )
        overview.add_row(
            str(table_index),
            table.location.path,
            table.environment.value,
            _short_text(metadata),
            str(len(table.rows)),
            "" if table.expected_column_count is None else str(table.expected_column_count),
            table.reliability.value,
            ", ".join(item.code for item in table.diagnostics),
        )
    console.print(overview)
    for table_index, table in enumerate(tables, start=1):
        if not table.rows:
            continue
        cells = Table(
            title=f"Table {table_index} cells: {table.location.path}",
            show_lines=True,
        )
        cells.add_column("Row", justify="right")
        cells.add_column("Cell", justify="right")
        cells.add_column("Logical", justify="right")
        cells.add_column("Row width", justify="right")
        cells.add_column("Span", justify="right")
        cells.add_column("Content")
        cells.add_column("Numeric candidates")
        cells.add_column("Formatting")
        cells.add_column("Reliability / limitations")
        for row in table.rows:
            for cell in row.cells:
                cells.add_row(
                    str(row.row_index),
                    str(cell.physical_index),
                    str(cell.logical_column_start),
                    str(row.logical_column_count),
                    str(cell.logical_column_span),
                    _short_text(cell.normalized_text),
                    _cell_numeric_summary(cell),
                    ", ".join(item.kind.value for item in cell.formatting),
                    " / ".join((cell.reliability.value, *cell.limitations)),
                )
        console.print(cells)


def _cell_numeric_summary(cell: LatexTableCell) -> str:
    return ", ".join(
        (
            reference.candidate.raw_text
            + (
                f" [{'/'.join(item.value for item in reference.formatting)}]"
                if reference.formatting
                else ""
            )
        )
        for reference in cell.numeric_references
    )


def _short_text(value: str, limit: int = 72) -> str:
    collapsed = " ".join(value.split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1]}…"


def _candidate_canonical(candidate: RawNumericCandidate) -> str:
    mean = str(candidate.value.canonical)
    if candidate.uncertainty is None:
        return mean
    return f"{mean} +/- {candidate.uncertainty.canonical}"


def _scan_payload(
    project_root: Path,
    configuration: ProjectConfiguration,
    result: PaperScanResult,
    classifications: ClaimClassificationResult,
    displayed: tuple[RawNumericCandidate, ...],
) -> dict[str, object]:
    return {
        "schema_version": "3",
        "command": "scan",
        "result_type": "paper_scan",
        "ok": not result.has_blocking_errors,
        "complete": result.complete,
        "project": project_root.name,
        "config_schema_version": configuration.schema_version,
        "summary": {
            "scanned_file_count": result.statistics.scanned_file_count,
            "total_bytes": result.statistics.total_bytes,
            "raw_candidate_count": result.statistics.candidate_count,
            "displayed_candidate_count": len(displayed),
            "likely_claim_count": classifications.statistics.likely_count,
            "possible_claim_count": classifications.statistics.possible_count,
            "ambiguous_claim_count": classifications.statistics.ambiguous_count,
            "non_experiment_claim_count": (classifications.statistics.non_experiment_count),
            "table_count": result.statistics.table_count,
            "parsed_table_count": result.statistics.parsed_table_count,
            "degraded_table_count": result.statistics.degraded_table_count,
            "unsupported_table_count": result.statistics.unsupported_table_count,
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
        "candidates": [_candidate_payload(candidate) for candidate in result.candidates],
        "claim_classifications": classification_payloads(classifications, result.candidates),
        "tables": [_table_payload(table) for table in result.tables],
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


def _table_payload(table: LatexTable) -> dict[str, object]:
    return {
        "environment": table.environment.value,
        "reliability": table.reliability.value,
        "location": _location_payload(table.location),
        "container": (
            {
                "environment": table.container_environment.value,
                "location": _location_payload(table.container_location),
            }
            if table.container_environment is not None and table.container_location is not None
            else None
        ),
        "caption": _table_text_payload(table.caption),
        "label": _table_text_payload(table.label),
        "column_spec": (
            {
                "raw_latex": table.column_spec.raw_latex,
                "expected_column_count": table.column_spec.expected_column_count,
                "location": _location_payload(table.column_spec.location),
            }
            if table.column_spec is not None
            else None
        ),
        "rows": [
            {
                "row_index": row.row_index,
                "logical_column_count": row.logical_column_count,
                "reliability": row.reliability.value,
                "location": _location_payload(row.location),
                "structure_markers": [
                    _structure_marker_payload(marker) for marker in row.structure_markers
                ],
                "cells": [_table_cell_payload(cell) for cell in row.cells],
            }
            for row in table.rows
        ],
        "structure_markers": [
            _structure_marker_payload(marker) for marker in table.structure_markers
        ],
        "diagnostics": [_diagnostic_payload(item) for item in table.diagnostics],
    }


def _table_text_payload(value: object) -> dict[str, object] | None:
    from metricproof.domain.paper import LatexTableText

    if value is None:
        return None
    if not isinstance(value, LatexTableText):
        raise TypeError("table text payload requires LatexTableText")
    return {
        "raw_text": value.raw_text,
        "normalized_text": value.normalized_text,
        "location": _location_payload(value.location),
    }


def _structure_marker_payload(value: object) -> dict[str, object]:
    from metricproof.domain.paper import LatexTableStructureMarker

    if not isinstance(value, LatexTableStructureMarker):
        raise TypeError("structure marker payload requires LatexTableStructureMarker")
    return {
        "kind": value.kind.value,
        "raw_latex": value.raw_latex,
        "location": _location_payload(value.location),
    }


def _table_cell_payload(cell: LatexTableCell) -> dict[str, object]:
    return {
        "physical_index": cell.physical_index,
        "logical_column_start": cell.logical_column_start,
        "logical_column_span": cell.logical_column_span,
        "multicolumn_format": cell.multicolumn_format,
        "location": _location_payload(cell.location),
        "content_location": _location_payload(cell.content_location),
        "raw_latex": cell.raw_latex,
        "normalized_text": cell.normalized_text,
        "is_empty": cell.is_empty,
        "reliability": cell.reliability.value,
        "limitations": list(cell.limitations),
        "formatting": [
            {
                "kind": item.kind.value,
                "location": _location_payload(item.location),
                "content_location": _location_payload(item.content_location),
            }
            for item in cell.formatting
        ],
        "numeric_references": [
            {
                "candidate_kind": reference.candidate.kind.value,
                "raw_text": reference.candidate.raw_text,
                "value": _numeric_payload(reference.candidate.value),
                "uncertainty": (
                    _numeric_payload(reference.candidate.uncertainty)
                    if reference.candidate.uncertainty is not None
                    else None
                ),
                "location": _location_payload(reference.candidate.location),
                "formatting": [item.value for item in reference.formatting],
            }
            for reference in cell.numeric_references
        ],
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
