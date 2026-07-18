"""Pure numeric and three-rule semantics tests."""

from __future__ import annotations

import re
from decimal import Decimal
from hashlib import sha256

import pytest

from metricproof.domain.claim_identity import (
    ClaimContext,
    ClaimFingerprint,
    ClaimIdentitySnapshot,
    IdentifiedClaim,
    StableClaimId,
)
from metricproof.domain.claims import (
    ClaimCandidateClassification,
    ClaimConfidence,
    ClaimDisposition,
    ClaimEvidence,
    ClaimKind,
    EvidenceDirection,
)
from metricproof.domain.links import (
    DerivedLink,
    DerivedOperand,
    DerivedOperation,
    DirectLink,
    LinkScale,
    MetricReference,
    NumericTolerance,
    RoundingPolicy,
    StandardDeviationMode,
)
from metricproof.domain.models import (
    MetricObservation,
    NumericKind,
    NumericUnit,
    NumericValue,
    Severity,
    SourceLocation,
)
from metricproof.domain.paper import (
    LatexSyntacticContext,
    NumericCandidateKind,
    RawNumericCandidate,
)
from metricproof.domain.registry import (
    ClaimRegistryEntry,
    ClaimRegistryStatus,
    IgnoreReason,
    IgnoreRecord,
)
from metricproof.domain.rules import (
    DerivedCalculationError,
    calculate_derived,
    check_missing_provenance,
    check_stale_value,
    check_wrong_delta,
    compare_claim_value,
)


def _claim(text: str) -> IdentifiedClaim:
    matches = tuple(re.finditer(r"[-+]?\d+(?:\.\d+)?(?:\\?%)?", text))
    assert matches
    match = matches[-1]
    raw_text = match.group()
    percent = raw_text.endswith(("%", "\\%"))
    numeric_text = raw_text.removesuffix("\\%").removesuffix("%")
    parsed = Decimal(numeric_text)
    decimal_places = len(numeric_text.partition(".")[2]) if "." in numeric_text else 0
    value = NumericValue(
        raw_text=raw_text,
        parsed=parsed,
        unit=NumericUnit.RATIO if percent else NumericUnit.SCALAR,
        kind=NumericKind.PERCENT if percent else NumericKind.DECIMAL,
        decimal_places=decimal_places,
        scale=Decimal("0.01") if percent else Decimal("1"),
    )
    location = SourceLocation(
        "main.tex",
        line=1,
        column=match.start() + 1,
        char_start=match.start(),
        char_end=match.end(),
    )
    candidate = RawNumericCandidate(
        kind=NumericCandidateKind.VALUE,
        raw_text=raw_text,
        value=value,
        location=location,
        context=LatexSyntacticContext.TEXT,
        environments=(),
        entry_paths=("main.tex",),
        include_chain=("main.tex",),
        prefix=text[: match.start()],
        suffix=text[match.end() :],
    )
    disposition = (
        ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM
        if "epochs" in text.casefold()
        else ClaimDisposition.LIKELY_EXPERIMENT_CLAIM
    )
    kind = (
        ClaimKind.DERIVED_RESULT
        if any(
            token in text.casefold() for token in ("improvement", "relative", "standard deviation")
        )
        else ClaimKind.DIRECT_RESULT
    )
    evidence = ClaimEvidence(
        reason_code="TEST_METRIC_CONTEXT",
        direction=EvidenceDirection.POSITIVE,
        score_impact=40,
        explanation="Synthetic test Claim contains an explicit metric context.",
        location=location,
    )
    classification = ClaimCandidateClassification(
        candidate=candidate,
        disposition=disposition,
        kind=kind,
        score=80 if disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM else 60,
        confidence=ClaimConfidence.HIGH,
        review_recommended=True,
        evidence=(evidence,),
    )
    digest = sha256(text.encode()).hexdigest()
    context = ClaimContext(
        summary=f"{text[: match.start()]}<claim>{text[match.end() :]}",
        structural_anchor="context=text|environment=document|command=none",
        prefix_anchor=text[: match.start()].casefold().strip(),
        suffix_anchor=text[match.end() :].casefold().strip(),
        syntactic_context="text",
        occurrence_ordinal=0,
    )
    fingerprint = ClaimFingerprint(
        version="1",
        digest=digest,
        path="main.tex",
        structural_anchor=context.structural_anchor,
        context_digest=digest[:20],
        semantic_digest=digest[20:40],
        components=(("path", "main.tex"),),
    )
    return IdentifiedClaim(
        claim_id=StableClaimId(f"clm_{digest[:20]}"),
        fingerprint=fingerprint,
        location=location,
        raw_text=raw_text,
        value=value,
        kind=kind,
        disposition=disposition,
        context=context,
        classification=classification,
        candidate_index=0,
    )


def _observation(run_id: str, metric: str, value: str) -> MetricObservation:
    source_file = f"runs/{run_id}.json"
    selector = f"metrics.{metric}"
    return MetricObservation.create(
        run_id=run_id,
        metric_name=metric,
        numeric=NumericValue(raw_text=value, parsed=Decimal(value)),
        source_file=source_file,
        source_selector=selector,
        location=SourceLocation(source_file, selector=selector),
    )


def _reference(
    observation: MetricObservation, scale: LinkScale = LinkScale.IDENTITY
) -> MetricReference:
    return MetricReference(
        source_file=observation.source_file,
        run_id=observation.run_id,
        metric_name=observation.metric_name,
        source_selector=observation.source_selector,
        scale=scale,
    )


def _derived(
    claim: IdentifiedClaim,
    operation: DerivedOperation,
    observations: tuple[MetricObservation, ...],
    *,
    output_unit: NumericUnit = NumericUnit.SCALAR,
    output_scale: LinkScale = LinkScale.IDENTITY,
    std_mode: StandardDeviationMode | None = None,
    rounding: int | None = None,
) -> DerivedLink:
    if operation in {DerivedOperation.SUBTRACTION, DerivedOperation.RELATIVE_CHANGE}:
        names = ("baseline", "candidate")
    else:
        names = tuple(f"value_{index:03d}" for index in range(len(observations)))
    return DerivedLink(
        claim_id=claim.claim_id,
        operation=operation,
        operands=tuple(
            DerivedOperand(name, _reference(observation))
            for name, observation in zip(names, observations, strict=True)
        ),
        output_unit=output_unit,
        output_scale=output_scale,
        confirmed_fingerprint=claim.fingerprint.digest,
        rounding=RoundingPolicy(decimal_places=rounding),
        standard_deviation_mode=std_mode,
    )


def test_display_precision_interval_is_half_open_for_percent_claim() -> None:
    claim = _claim(r"Accuracy reaches 87.2\%.")

    inside = compare_claim_value(claim, Decimal("0.872499"), NumericTolerance())
    upper_edge = compare_claim_value(claim, Decimal("0.8725"), NumericTolerance())

    assert inside.matches
    assert inside.base_lower == Decimal("0.8715")
    assert inside.base_upper == Decimal("0.8725")
    assert not upper_edge.matches


def test_absolute_and_relative_tolerance_expand_display_interval() -> None:
    claim = _claim("Accuracy reaches 100.0.")

    absolute = compare_claim_value(
        claim,
        Decimal("100.06"),
        NumericTolerance(absolute=Decimal("0.02")),
    )
    relative = compare_claim_value(
        claim,
        Decimal("100.06"),
        NumericTolerance(relative=Decimal("0.0002")),
    )

    assert absolute.matches
    assert absolute.effective_tolerance == Decimal("0.02")
    assert relative.matches
    assert relative.effective_tolerance == Decimal("0.020012")


def test_two_hundred_display_values_follow_deterministic_interval_boundaries() -> None:
    claim = _claim("Accuracy reaches 50.00.")
    values = tuple(Decimal("49.990") + Decimal(index) / Decimal("10000") for index in range(200))

    first = tuple(compare_claim_value(claim, value, NumericTolerance()) for value in values)
    second = tuple(compare_claim_value(claim, value, NumericTolerance()) for value in values)

    assert first == second
    assert sum(item.matches for item in first) == 100
    assert not first[49].matches
    assert first[50].matches
    assert first[149].matches
    assert not first[150].matches


def test_stale_value_exact_rounding_and_true_mismatch() -> None:
    claim = _claim(r"Accuracy reaches 87.2\%.")
    exact = _observation("run", "accuracy", "0.872")
    rounded = _observation("rounded", "accuracy", "0.87249")
    stale = _observation("stale", "accuracy", "0.88")

    assert (
        check_stale_value(
            claim,
            DirectLink(
                claim.claim_id,
                _reference(exact),
                claim.fingerprint.digest,
            ),
            exact,
            NumericTolerance(),
        )
        == ()
    )
    assert (
        check_stale_value(
            claim,
            DirectLink(
                claim.claim_id,
                _reference(rounded),
                claim.fingerprint.digest,
            ),
            rounded,
            NumericTolerance(),
        )
        == ()
    )
    diagnostics = check_stale_value(
        claim,
        DirectLink(
            claim.claim_id,
            _reference(stale),
            claim.fingerprint.digest,
        ),
        stale,
        NumericTolerance(),
    )
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic.code == "STALE_VALUE"
    assert diagnostic.observed == Decimal("0.872")
    assert diagnostic.expected == Decimal("0.88")
    assert diagnostic.claim_id == claim.claim_id.value
    assert diagnostic.evidence
    assert diagnostic.remediation
    assert diagnostic.uncertainties


def test_stale_value_respects_explicit_percent_to_fraction_scale() -> None:
    claim = _claim(r"Accuracy reaches 87.2\%.")
    observation = _observation("run", "accuracy", "87.2")
    link = DirectLink(
        claim.claim_id,
        _reference(observation, LinkScale.PERCENT_TO_FRACTION),
        claim.fingerprint.digest,
    )

    assert check_stale_value(claim, link, observation, NumericTolerance()) == ()


@pytest.mark.parametrize(
    ("operation", "values", "expected", "mode"),
    [
        (DerivedOperation.SUBTRACTION, ("0.7", "0.8"), "0.1", None),
        (DerivedOperation.RELATIVE_CHANGE, ("0.5", "0.55"), "0.1", None),
        (DerivedOperation.MEAN, ("1", "2", "3"), "2", None),
        (
            DerivedOperation.STANDARD_DEVIATION,
            ("1", "2", "3"),
            "1",
            StandardDeviationMode.SAMPLE,
        ),
    ],
)
def test_derived_operations_are_exact_and_bounded(
    operation: DerivedOperation,
    values: tuple[str, ...],
    expected: str,
    mode: StandardDeviationMode | None,
) -> None:
    claim = _claim("Accuracy improvement is 2.0.")
    observations = tuple(
        _observation(f"run-{index}", "accuracy", value) for index, value in enumerate(values)
    )
    link = _derived(claim, operation, observations, std_mode=mode)

    calculation = calculate_derived(link, observations)

    assert calculation.rounded_value == Decimal(expected)


def test_percentage_points_are_not_relative_percent() -> None:
    claim = _claim("Accuracy improvement is 3.1 percentage points.")
    observations = (
        _observation("baseline", "accuracy", "0.841"),
        _observation("candidate", "accuracy", "0.872"),
    )
    link = _derived(
        claim,
        DerivedOperation.SUBTRACTION,
        observations,
        output_unit=NumericUnit.PERCENT_POINTS,
    )

    calculation = calculate_derived(link, observations)

    assert calculation.raw_value == Decimal("0.031")
    assert calculation.unit_adjusted_value == Decimal("3.100")
    assert calculation.rounded_value == Decimal("3.100")


def test_population_standard_deviation_and_rounding_are_explicit() -> None:
    claim = _claim("Accuracy standard deviation is 0.82.")
    observations = (
        _observation("a", "accuracy", "0"),
        _observation("b", "accuracy", "1"),
        _observation("c", "accuracy", "2"),
    )
    link = _derived(
        claim,
        DerivedOperation.STANDARD_DEVIATION,
        observations,
        std_mode=StandardDeviationMode.POPULATION,
        rounding=2,
    )

    calculation = calculate_derived(link, observations)

    assert calculation.rounded_value == Decimal("0.82")


def test_wrong_delta_only_reports_a_computable_mismatch() -> None:
    claim = _claim("Accuracy improvement is 0.20.")
    observations = (
        _observation("baseline", "accuracy", "0.7"),
        _observation("candidate", "accuracy", "0.8"),
    )
    link = _derived(claim, DerivedOperation.SUBTRACTION, observations)

    diagnostics = check_wrong_delta(claim, link, observations, NumericTolerance())

    assert len(diagnostics) == 1
    assert diagnostics[0].code == "WRONG_DELTA"
    assert diagnostics[0].observed == Decimal("0.20")
    assert diagnostics[0].expected == Decimal("0.1")
    assert len(diagnostics[0].related_sources) == 2


def test_relative_change_zero_baseline_is_a_controlled_link_problem() -> None:
    claim = _claim(r"Accuracy relative improvement is 10\%.")
    observations = (
        _observation("baseline", "accuracy", "0"),
        _observation("candidate", "accuracy", "1"),
    )
    link = _derived(claim, DerivedOperation.RELATIVE_CHANGE, observations)

    with pytest.raises(DerivedCalculationError, match="baseline is zero"):
        calculate_derived(link, observations)


def test_missing_provenance_likely_possible_and_ignore_semantics() -> None:
    likely = _claim("Accuracy reaches 0.91.")
    diagnostic = check_missing_provenance(
        likely,
        None,
        include_possible=False,
        severity=Severity.WARNING,
    )
    assert len(diagnostic) == 1
    assert diagnostic[0].code == "MISSING_PROVENANCE"
    assert diagnostic[0].severity is Severity.WARNING

    ignored = ClaimRegistryEntry(
        identity=ClaimIdentitySnapshot.from_claim(likely),
        status=ClaimRegistryStatus.IGNORED,
        ignore=IgnoreRecord(IgnoreReason.USER_DECISION, "reviewed"),
    )
    assert (
        check_missing_provenance(
            likely,
            ignored,
            include_possible=True,
            severity=Severity.WARNING,
        )
        == ()
    )

    possible = _claim("Accuracy uses 100 epochs.")
    assert possible.disposition.value == "possible_experiment_claim"
    assert (
        check_missing_provenance(
            possible,
            None,
            include_possible=False,
            severity=Severity.INFO,
        )
        == ()
    )
    assert (
        len(
            check_missing_provenance(
                possible,
                None,
                include_possible=True,
                severity=Severity.INFO,
            )
        )
        == 1
    )
