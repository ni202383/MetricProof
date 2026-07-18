"""Pure Decimal semantics for the three Stage 5 consistency rules."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from metricproof.domain.claim_identity import IdentifiedClaim
from metricproof.domain.claims import ClaimDisposition
from metricproof.domain.diagnostics import (
    CheckDiagnostic,
    CheckDiagnosticKind,
    make_check_diagnostic,
    make_check_evidence,
)
from metricproof.domain.links import (
    DerivedLink,
    DerivedOperation,
    DirectLink,
    NumericTolerance,
    StandardDeviationMode,
)
from metricproof.domain.models import MetricObservation, NumericUnit, Severity, SourceLocation
from metricproof.domain.registry import ClaimRegistryEntry


@dataclass(frozen=True, slots=True)
class NumericComparison:
    paper_value: Decimal
    computed_value: Decimal
    base_lower: Decimal
    base_upper: Decimal
    effective_tolerance: Decimal
    accepted_lower: Decimal
    accepted_upper: Decimal
    matches: bool


@dataclass(frozen=True, slots=True)
class DerivedCalculation:
    operation: DerivedOperation
    operand_values: tuple[tuple[str, Decimal], ...]
    raw_value: Decimal
    unit_adjusted_value: Decimal
    scaled_value: Decimal
    rounded_value: Decimal
    formula: str


class DerivedCalculationError(ValueError):
    """A controlled reason why a confirmed derived link cannot be evaluated."""


def compare_claim_value(
    claim: IdentifiedClaim,
    computed_value: Decimal,
    tolerance: NumericTolerance,
) -> NumericComparison:
    """Compare exact values using display precision plus absolute/relative tolerance."""

    paper_value = claim.value.canonical
    assert paper_value is not None
    if not computed_value.is_finite():
        raise ValueError("computed comparison values must be finite")
    places = claim.value.decimal_places
    half_step = (
        abs(Decimal("0.5").scaleb(-places) * claim.value.scale)
        if places is not None
        else Decimal("0")
    )
    base_lower = paper_value - half_step
    base_upper = paper_value + half_step
    effective_tolerance = max(
        tolerance.absolute,
        tolerance.relative * max(abs(paper_value), abs(computed_value)),
    )
    accepted_lower = base_lower - effective_tolerance
    accepted_upper = base_upper + effective_tolerance
    matches = (
        accepted_lower <= computed_value < accepted_upper
        if half_step > 0
        else accepted_lower <= computed_value <= accepted_upper
    )
    return NumericComparison(
        paper_value=paper_value,
        computed_value=computed_value,
        base_lower=base_lower,
        base_upper=base_upper,
        effective_tolerance=effective_tolerance,
        accepted_lower=accepted_lower,
        accepted_upper=accepted_upper,
        matches=matches,
    )


def check_stale_value(
    claim: IdentifiedClaim,
    link: DirectLink,
    observation: MetricObservation,
    tolerance: NumericTolerance,
) -> tuple[CheckDiagnostic, ...]:
    """Return STALE_VALUE only when a valid DirectLink is outside its accepted interval."""

    if link.claim_id != claim.claim_id:
        raise ValueError("DirectLink Claim ID must match the checked Claim")
    computed = link.metric.scale.apply(observation.value)
    comparison = compare_claim_value(claim, computed, tolerance)
    if comparison.matches:
        return ()
    evidence = (
        make_check_evidence(
            kind="paper_claim",
            summary="Paper Claim display value and accepted Decimal interval.",
            location=claim.location,
            details=(
                f"raw={claim.raw_text}",
                f"canonical={comparison.paper_value}",
                f"base_interval=[{comparison.base_lower},{comparison.base_upper})",
                f"effective_tolerance={comparison.effective_tolerance}",
            ),
        ),
        make_check_evidence(
            kind="metric_observation",
            summary="Current linked metric value after the explicit Link scale.",
            location=observation.location,
            details=(
                f"run_id={observation.run_id}",
                f"metric={observation.metric_name}",
                f"raw_value={observation.value}",
                f"scale={link.metric.scale.value}",
                f"converted={computed}",
            ),
        ),
    )
    return (
        make_check_diagnostic(
            kind=CheckDiagnosticKind.RULE,
            code="STALE_VALUE",
            severity=Severity.ERROR,
            message=(
                "The linked experiment value does not match this paper Claim within "
                "its display precision and configured tolerance."
            ),
            location=claim.location,
            claim_id=claim.claim_id.value,
            observed=comparison.paper_value,
            expected=computed,
            evidence=evidence,
            confidence=Decimal("1"),
            related_sources=(observation.location,),
            remediation=(
                "Review the selected run/metric and scale, then update the paper value or relink "
                "the Claim if appropriate."
            ),
            uncertainties=(
                "This is a representation consistency finding, not a scientific validity judgment.",
            ),
        ),
    )


def calculate_derived(
    link: DerivedLink,
    observations: tuple[MetricObservation, ...],
) -> DerivedCalculation:
    """Evaluate one bounded, single-layer DerivedLink with exact Decimal arithmetic."""

    if len(observations) != len(link.operands):
        raise DerivedCalculationError("every derived operand requires one resolved observation")
    values: list[tuple[str, Decimal]] = []
    for operand, observation in zip(link.operands, observations, strict=True):
        reference = operand.metric
        if (
            observation.source_file,
            observation.run_id,
            observation.metric_name,
            observation.source_selector,
        ) != (
            reference.source_file,
            reference.run_id,
            reference.metric_name,
            reference.source_selector,
        ):
            raise DerivedCalculationError(
                "resolved observation does not match its operand reference"
            )
        values.append((operand.name, reference.scale.apply(observation.value)))
    by_name = dict(values)
    if link.operation is DerivedOperation.SUBTRACTION:
        raw = by_name["candidate"] - by_name["baseline"]
        formula = "candidate - baseline"
    elif link.operation is DerivedOperation.RELATIVE_CHANGE:
        baseline = by_name["baseline"]
        if baseline == 0:
            raise DerivedCalculationError("relative_change is undefined when baseline is zero")
        raw = (by_name["candidate"] - baseline) / abs(baseline)
        formula = "(candidate - baseline) / abs(baseline)"
    elif link.operation is DerivedOperation.MEAN:
        raw = sum(by_name.values(), Decimal("0")) / Decimal(len(by_name))
        formula = "sum(values) / count(values)"
    elif link.operation is DerivedOperation.STANDARD_DEVIATION:
        raw = _standard_deviation(tuple(by_name.values()), link.standard_deviation_mode)
        formula = (
            "sqrt(sum((x - mean)^2) / (N - 1))"
            if link.standard_deviation_mode is StandardDeviationMode.SAMPLE
            else "sqrt(sum((x - mean)^2) / N)"
        )
    else:  # pragma: no cover - exhaustive enum guard
        raise DerivedCalculationError(f"unsupported derived operation: {link.operation}")

    if link.output_unit is NumericUnit.PERCENT_POINTS:
        if link.operation is not DerivedOperation.SUBTRACTION:
            raise DerivedCalculationError(
                "percent_points output is only valid for subtraction in the Stage 5 MVP"
            )
        unit_adjusted = raw * Decimal("100")
    else:
        unit_adjusted = raw
    scaled = link.output_scale.apply(unit_adjusted)
    rounded = link.rounding.apply(scaled)
    return DerivedCalculation(
        operation=link.operation,
        operand_values=tuple(values),
        raw_value=raw,
        unit_adjusted_value=unit_adjusted,
        scaled_value=scaled,
        rounded_value=rounded,
        formula=formula,
    )


def check_wrong_delta(
    claim: IdentifiedClaim,
    link: DerivedLink,
    observations: tuple[MetricObservation, ...],
    tolerance: NumericTolerance,
) -> tuple[CheckDiagnostic, ...]:
    """Return WRONG_DELTA only for a fully resolved, computable DerivedLink mismatch."""

    if link.claim_id != claim.claim_id:
        raise ValueError("DerivedLink Claim ID must match the checked Claim")
    calculation = calculate_derived(link, observations)
    comparison = compare_claim_value(claim, calculation.rounded_value, tolerance)
    if comparison.matches:
        return ()
    operand_evidence = tuple(
        make_check_evidence(
            kind="derived_operand",
            summary=f"Resolved operand {operand.name!r} from a confirmed metric reference.",
            location=observation.location,
            details=(
                f"run_id={observation.run_id}",
                f"metric={observation.metric_name}",
                f"source_value={observation.value}",
                f"operand_scale={operand.metric.scale.value}",
                f"operation_value={value}",
            ),
        )
        for operand, observation, (_, value) in zip(
            link.operands,
            observations,
            calculation.operand_values,
            strict=True,
        )
    )
    evidence = (
        make_check_evidence(
            kind="paper_claim",
            summary="Paper Claim display value and accepted Decimal interval.",
            location=claim.location,
            details=(
                f"raw={claim.raw_text}",
                f"canonical={comparison.paper_value}",
                f"accepted=[{comparison.accepted_lower},{comparison.accepted_upper})",
            ),
        ),
        *operand_evidence,
        make_check_evidence(
            kind="derived_calculation",
            summary="Recomputed the confirmed bounded derived operation.",
            details=(
                f"operation={link.operation.value}",
                f"formula={calculation.formula}",
                f"raw={calculation.raw_value}",
                f"unit_adjusted={calculation.unit_adjusted_value}",
                f"output_scale={link.output_scale.value}",
                f"scaled={calculation.scaled_value}",
                f"rounded={calculation.rounded_value}",
                f"rounding_mode={link.rounding.mode.value}",
                f"decimal_places={link.rounding.decimal_places}",
            ),
        ),
    )
    return (
        make_check_diagnostic(
            kind=CheckDiagnosticKind.RULE,
            code="WRONG_DELTA",
            severity=Severity.ERROR,
            message=(
                "The displayed derived Claim does not match the recomputed confirmed operands "
                "within display precision and configured tolerance."
            ),
            location=claim.location,
            claim_id=claim.claim_id.value,
            observed=comparison.paper_value,
            expected=calculation.rounded_value,
            evidence=evidence,
            confidence=Decimal("1"),
            related_sources=tuple(item.location for item in observations),
            remediation=(
                "Review the operation, operand runs, percentage/percentage-point semantics, and "
                "rounding policy before updating the paper or link."
            ),
            uncertainties=("This finding checks the confirmed arithmetic representation only.",),
        ),
    )


def check_missing_provenance(
    claim: IdentifiedClaim,
    entry: ClaimRegistryEntry | None,
    *,
    include_possible: bool,
    severity: Severity,
) -> tuple[CheckDiagnostic, ...]:
    """Report only current likely (or explicitly enabled possible) unlinked Claims."""

    if entry is not None:
        return ()
    applicable = claim.disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM or (
        include_possible and claim.disposition is ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM
    )
    if not applicable:
        return ()
    classification = claim.classification
    evidence = tuple(
        make_check_evidence(
            kind="claim_classification",
            summary=item.explanation,
            location=item.location,
            details=(
                f"reason_code={item.reason_code}",
                f"direction={item.direction.value}",
                f"score_impact={item.score_impact}",
                *item.structural_context,
            ),
        )
        for item in classification.evidence
        if item.score_impact > 0
    )
    registry_evidence = make_check_evidence(
        kind="claim_registry",
        summary="No active Link or explicit IgnoreRecord exists for this current Claim.",
        location=claim.location,
        details=(f"claim_id={claim.claim_id.value}",),
    )
    return (
        make_check_diagnostic(
            kind=CheckDiagnosticKind.RULE,
            code="MISSING_PROVENANCE",
            severity=severity,
            message=(
                "This likely experimental Claim has no confirmed local metric provenance or "
                "explicit ignore decision."
            ),
            location=claim.location,
            claim_id=claim.claim_id.value,
            observed=claim.raw_text,
            expected="active link or explicit ignore",
            evidence=(*evidence, registry_evidence),
            confidence=Decimal(classification.score) / Decimal("100"),
            remediation=(
                "Run metricproof link to confirm a source, or explicitly ignore the Claim after "
                "manual review."
            ),
            uncertainties=(
                "Claim classification is heuristic and does not establish scientific significance.",
            ),
        ),
    )


def make_link_problem(
    *,
    code: str,
    claim_id: str,
    location: SourceLocation,
    message: str,
    details: tuple[str, ...],
    remediation: str,
) -> CheckDiagnostic:
    """Create a specific link/migration diagnostic that suppresses misleading rule output."""

    evidence = (
        make_check_evidence(
            kind="link_resolution",
            summary="A confirmed or retained link could not be evaluated safely.",
            location=location,
            details=details,
        ),
    )
    return make_check_diagnostic(
        kind=CheckDiagnosticKind.LINK,
        code=code,
        severity=Severity.ERROR,
        message=message,
        location=location,
        claim_id=claim_id,
        evidence=evidence,
        confidence=Decimal("1"),
        remediation=remediation,
        uncertainties=("No STALE_VALUE or WRONG_DELTA conclusion was produced for this link.",),
    )


def _standard_deviation(
    values: tuple[Decimal, ...],
    mode: StandardDeviationMode | None,
) -> Decimal:
    if mode is None:
        raise DerivedCalculationError("standard_deviation requires sample or population mode")
    if len(values) < 2:
        raise DerivedCalculationError("standard_deviation requires at least two operands")
    mean = sum(values, Decimal("0")) / Decimal(len(values))
    squared = sum(((value - mean) ** 2 for value in values), Decimal("0"))
    denominator = Decimal(len(values) - 1 if mode is StandardDeviationMode.SAMPLE else len(values))
    return (squared / denominator).sqrt()
