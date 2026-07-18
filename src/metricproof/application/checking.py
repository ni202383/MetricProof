"""Application orchestration for the Stage 5 unified CheckResult."""

from __future__ import annotations

from collections import Counter

from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.linking import (
    LinkReviewItem,
    LinkReviewStatus,
    build_link_session,
)
from metricproof.domain.diagnostics import (
    CHECK_RESULT_SCHEMA_VERSION,
    CheckDiagnostic,
    CheckDiagnosticKind,
    CheckResult,
    CheckSummary,
    check_diagnostic_sort_key,
    make_check_diagnostic,
)
from metricproof.domain.links import DerivedLink, DirectLink, MetricReference, NumericTolerance
from metricproof.domain.models import (
    DiagnosticKind,
    ExperimentCatalog,
    InputDiagnostic,
    MetricObservation,
    SourceLocation,
)
from metricproof.domain.paper import PaperScanResult
from metricproof.domain.registry import ClaimRegistry
from metricproof.domain.rules import (
    DerivedCalculationError,
    check_missing_provenance,
    check_stale_value,
    check_wrong_delta,
    make_link_problem,
)

CORE_RULE_CODES = frozenset({"STALE_VALUE", "WRONG_DELTA", "MISSING_PROVENANCE"})


def check_project(
    scan: PaperScanResult,
    configuration: ProjectConfiguration,
    catalog: ExperimentCatalog,
    registry: ClaimRegistry,
    *,
    tool_version: str,
    selected_rules: frozenset[str] = CORE_RULE_CODES,
) -> CheckResult:
    """Build one session, run selected pure rules, and return the sole renderer input."""

    unknown = selected_rules - CORE_RULE_CODES
    if unknown:
        raise ValueError(f"unsupported Stage 5 rule codes: {sorted(unknown)!r}")
    session = build_link_session(scan, configuration, catalog, registry)
    diagnostics: list[CheckDiagnostic] = [
        *(_input_diagnostic(item) for item in scan.diagnostics),
        *(_input_diagnostic(item) for item in catalog.diagnostics),
    ]
    if session.identity_collisions:
        location = _fallback_location(scan, configuration)
        diagnostics.extend(
            make_link_problem(
                code="LINK_IDENTITY_COLLISION",
                claim_id=summary.partition(":")[0],
                location=location,
                message=(
                    "Multiple current Claims share a stable identity; "
                    "no automatic binding was used."
                ),
                details=(summary,),
                remediation=(
                    "Review the colliding Claims and change the surrounding source context."
                ),
            )
            for summary in session.identity_collisions
        )

    has_blocking_inputs = scan.has_blocking_errors or catalog.has_blocking_errors
    if not has_blocking_inputs and not session.identity_collisions:
        for item in session.items:
            diagnostics.extend(_check_item(item, catalog, configuration, selected_rules))

    ordered = tuple(sorted(_deduplicate(diagnostics), key=check_diagnostic_sort_key))
    registry_counts = Counter(item.status.value for item in session.items)
    migration_counts = Counter(
        item.migration.status.value for item in session.items if item.migration is not None
    )
    diagnostic_counts = Counter(item.code for item in ordered)
    severity_counts = Counter(item.severity.value for item in ordered)
    return CheckResult(
        schema_version=CHECK_RESULT_SCHEMA_VERSION,
        tool_version=tool_version,
        project=".",
        summary=CheckSummary(
            checked_claim_count=sum(item.claim is not None for item in session.items),
            registry_counts=tuple(sorted(registry_counts.items())),
            migration_counts=tuple(sorted(migration_counts.items())),
            diagnostic_counts=tuple(sorted(diagnostic_counts.items())),
            severity_counts=tuple(sorted(severity_counts.items())),
        ),
        diagnostics=ordered,
    )


def _check_item(
    item: LinkReviewItem,
    catalog: ExperimentCatalog,
    configuration: ProjectConfiguration,
    selected_rules: frozenset[str],
) -> tuple[CheckDiagnostic, ...]:
    if item.status is LinkReviewStatus.IGNORED:
        return ()
    if item.status in {LinkReviewStatus.AMBIGUOUS, LinkReviewStatus.MISSING}:
        return (_migration_problem(item),)
    if item.status is LinkReviewStatus.BROKEN:
        return (_broken_link_problem(item, catalog),)
    if item.status is LinkReviewStatus.UNLINKED:
        if item.claim is None or "MISSING_PROVENANCE" not in selected_rules:
            return ()
        return check_missing_provenance(
            item.claim,
            None,
            include_possible=(configuration.rule_policy.include_possible_missing_provenance),
            severity=configuration.rule_policy.missing_provenance_severity,
        )
    if item.claim is None or item.existing_entry is None or item.existing_entry.link is None:
        raise ValueError("active review items require a current Claim and retained Link")
    link = item.existing_entry.link
    if isinstance(link, DirectLink):
        if "STALE_VALUE" not in selected_rules:
            return ()
        observation = _find_observation(link.metric, catalog)
        if observation is None:
            return (_broken_link_problem(item, catalog),)
        tolerance = link.tolerance_override or configuration.rule_policy.tolerance_for(
            link.metric.metric_name
        )
        return check_stale_value(item.claim, link, observation, tolerance)
    if "WRONG_DELTA" not in selected_rules:
        return ()
    observations = tuple(_find_observation(operand.metric, catalog) for operand in link.operands)
    if any(observation is None for observation in observations):
        return (_broken_link_problem(item, catalog),)
    resolved = tuple(observation for observation in observations if observation is not None)
    tolerance = link.tolerance_override or _derived_tolerance(link, configuration)
    try:
        return check_wrong_delta(item.claim, link, resolved, tolerance)
    except DerivedCalculationError as error:
        return (
            make_link_problem(
                code="LINK_DERIVATION_UNDEFINED",
                claim_id=item.claim_id,
                location=item.claim.location,
                message=(
                    "The confirmed derived link cannot be evaluated safely, so no "
                    "WRONG_DELTA conclusion was produced."
                ),
                details=(str(error),),
                remediation="Review the operation, operands, output unit, scale, and std mode.",
            ),
        )


def _derived_tolerance(
    link: DerivedLink,
    configuration: ProjectConfiguration,
) -> NumericTolerance:
    metrics = {operand.metric.metric_name for operand in link.operands}
    if len(metrics) == 1:
        return configuration.rule_policy.tolerance_for(next(iter(metrics)))
    return configuration.rule_policy.default_tolerance


def _find_observation(
    reference: MetricReference,
    catalog: ExperimentCatalog,
) -> MetricObservation | None:
    return next(
        (
            item
            for item in catalog.observations
            if (
                item.source_file,
                item.run_id,
                item.metric_name,
                item.source_selector,
            )
            == (
                reference.source_file,
                reference.run_id,
                reference.metric_name,
                reference.source_selector,
            )
        ),
        None,
    )


def _broken_link_problem(
    item: LinkReviewItem,
    catalog: ExperimentCatalog,
) -> CheckDiagnostic:
    entry = item.existing_entry
    if entry is None or entry.link is None:
        raise ValueError("broken review items require a retained Link")
    references = (
        (entry.link.metric,)
        if isinstance(entry.link, DirectLink)
        else tuple(operand.metric for operand in entry.link.operands)
    )
    missing = tuple(
        sorted(
            f"{reference.source_file}:{reference.run_id}:{reference.metric_name}:"
            f"{reference.source_selector}"
            for reference in references
            if _find_observation(reference, catalog) is None
        )
    )
    location = item.claim.location if item.claim is not None else entry.identity.location
    return make_link_problem(
        code="LINK_SOURCE_MISSING",
        claim_id=item.claim_id,
        location=location,
        message=(
            "A confirmed metric source is unavailable; the retained link was not deleted and "
            "no numeric mismatch rule was asserted."
        ),
        details=missing or ("the retained link is marked broken",),
        remediation="Restore the declared source or run metricproof link --show-broken to relink.",
    )


def _migration_problem(item: LinkReviewItem) -> CheckDiagnostic:
    entry = item.existing_entry
    if entry is None:
        raise ValueError("migration problems require a retained registry entry")
    status = item.status.value
    migration = item.migration
    details = (
        (
            f"migration_status={migration.status.value}",
            f"method={migration.method.value}",
            f"score={migration.score}",
            *migration.conflicts,
        )
        if migration is not None
        else (f"review_status={status}",)
    )
    return make_link_problem(
        code="LINK_CLAIM_AMBIGUOUS" if status == "ambiguous" else "LINK_CLAIM_MISSING",
        claim_id=item.claim_id,
        location=entry.identity.location,
        message=(
            "The retained Claim cannot be mapped uniquely to the current paper; its link was "
            "not evaluated or deleted."
        ),
        details=details,
        remediation="Run metricproof link --show-broken and confirm the current Claim manually.",
    )


def _input_diagnostic(item: InputDiagnostic) -> CheckDiagnostic:
    kind = {
        DiagnosticKind.INPUT: CheckDiagnosticKind.INPUT,
        DiagnosticKind.LIMITATION: CheckDiagnosticKind.LIMITATION,
        DiagnosticKind.INTERNAL: CheckDiagnosticKind.INTERNAL,
    }[item.kind]
    return make_check_diagnostic(
        kind=kind,
        code=item.code,
        severity=item.severity,
        message=item.message,
        location=item.location,
        observed=item.observed,
        expected=item.expected,
        evidence=item.evidence,
        confidence=item.confidence,
        remediation=item.remediation,
    )


def _fallback_location(
    scan: PaperScanResult,
    configuration: ProjectConfiguration,
) -> SourceLocation:
    if scan.candidates:
        return scan.candidates[0].location
    path = configuration.paper_paths[0] if configuration.paper_paths else ".metricproof/config.yml"
    return SourceLocation(path)


def _deduplicate(diagnostics: list[CheckDiagnostic]) -> tuple[CheckDiagnostic, ...]:
    return tuple({item.diagnostic_id: item for item in diagnostics}.values())
