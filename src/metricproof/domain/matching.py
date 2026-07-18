"""Deterministic, explainable Claim-to-metric candidate matching."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from metricproof.domain.claim_identity import IdentifiedClaim
from metricproof.domain.claims import ClaimKind
from metricproof.domain.links import (
    DerivedOperand,
    DerivedOperation,
    LinkScale,
    MetricReference,
    StandardDeviationMode,
    metric_reference_sort_key,
)
from metricproof.domain.models import ExperimentCatalog, MetricObservation, NumericUnit
from metricproof.domain.paper import NumericCandidateKind

MATCH_MINIMUM_SCORE = 20
MATCH_AMBIGUITY_MARGIN = 8
MAX_DERIVED_GROUP_SIZE = 200

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_DERIVED_CUE_PATTERN = re.compile(
    r"\b(improv(?:e|es|ed|ement)?|increase[sd]?|decrease[sd]?|difference|delta|"
    r"gain(?:ed|s)?|drop(?:ped|s)?|reduc(?:e|ed|tion)|from|to)\b"
)
_RELATIVE_CUE_PATTERN = re.compile(r"\b(relative|percent|percentage)\b|%")
_POINT_CUE_PATTERN = re.compile(r"\bpercentage\s+points?\b|\bpoints?\b")


class LinkSuggestionType(StrEnum):
    DIRECT = "direct"
    DERIVED = "derived"


@dataclass(frozen=True, slots=True)
class MatchFeature:
    """One reviewable contribution to a candidate's total score."""

    code: str
    contribution: int
    summary: str

    def __post_init__(self) -> None:
        if not self.code.strip() or not self.summary.strip():
            raise ValueError("match features require a code and summary")
        if not -100 <= self.contribution <= 100:
            raise ValueError("match feature contributions must be between -100 and 100")


@dataclass(frozen=True, slots=True)
class CandidateMatch:
    """A suggestion only; it is never a confirmed persistent Link."""

    claim_id: str
    suggestion_type: LinkSuggestionType
    score: int
    features: tuple[MatchFeature, ...]
    uncertainties: tuple[str, ...]
    suggested_scale: LinkScale
    metric: MetricReference | None = None
    operation: DerivedOperation | None = None
    operands: tuple[DerivedOperand, ...] = ()
    output_unit: NumericUnit | None = None
    standard_deviation_mode: StandardDeviationMode | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("candidate match scores must be between 0 and 100")
        if tuple(sorted(set(self.uncertainties))) != self.uncertainties:
            raise ValueError("candidate uncertainties must be unique and sorted")
        expected = max(0, min(100, sum(item.contribution for item in self.features)))
        if self.score != expected:
            raise ValueError("candidate match score must equal its bounded feature sum")
        if self.suggestion_type is LinkSuggestionType.DIRECT:
            if self.metric is None or self.operation is not None or self.operands:
                raise ValueError("direct candidates require exactly one metric reference")
            if self.output_unit is not None or self.standard_deviation_mode is not None:
                raise ValueError("direct candidates cannot define derived output semantics")
        else:
            if self.metric is not None or self.operation is None or not self.operands:
                raise ValueError("derived candidates require an operation and operands")
            if self.output_unit is None:
                raise ValueError("derived candidates require an output unit")


@dataclass(frozen=True, slots=True)
class ClaimMatchResult:
    """Stable candidate ranking and its explicit ambiguity state for one Claim."""

    claim: IdentifiedClaim
    candidates: tuple[CandidateMatch, ...]
    ambiguous: bool
    uncertainties: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if tuple(sorted(self.candidates, key=candidate_match_sort_key)) != self.candidates:
            raise ValueError("Claim match candidates must use stable score ordering")
        if tuple(sorted(set(self.uncertainties))) != self.uncertainties:
            raise ValueError("Claim match uncertainties must be unique and sorted")


def suggest_claim_matches(
    claim: IdentifiedClaim,
    catalog: ExperimentCatalog,
    metric_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> ClaimMatchResult:
    """Rank explainable direct and clear derived candidates without persisting anything."""

    aliases = _aliases_by_metric(metric_aliases)
    context = _normalized_context(claim)
    candidates = [
        candidate
        for observation in catalog.observations
        if (candidate := _direct_candidate(claim, observation, aliases, context)) is not None
    ]
    candidates.extend(_derived_candidates(claim, catalog, aliases, context))
    ordered = tuple(sorted(candidates, key=candidate_match_sort_key))
    ambiguous = len(ordered) > 1 and ordered[0].score - ordered[1].score < MATCH_AMBIGUITY_MARGIN
    uncertainties: list[str] = []
    if not ordered:
        uncertainties.append("no candidate met the deterministic matching threshold")
    elif ambiguous:
        uncertainties.append("the leading candidates are too close to select automatically")
    return ClaimMatchResult(
        claim=claim,
        candidates=ordered,
        ambiguous=ambiguous,
        uncertainties=tuple(sorted(uncertainties)),
    )


def suggest_all_claim_matches(
    claims: tuple[IdentifiedClaim, ...],
    catalog: ExperimentCatalog,
    metric_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[ClaimMatchResult, ...]:
    """Match a prepared Claim set while reusing the already-loaded catalog."""

    return tuple(suggest_claim_matches(claim, catalog, metric_aliases) for claim in claims)


def candidate_match_sort_key(candidate: CandidateMatch) -> tuple[object, ...]:
    """Prefer score, then DirectLink, then stable source/operation identities."""

    kind_order = 0 if candidate.suggestion_type is LinkSuggestionType.DIRECT else 1
    if candidate.metric is not None:
        identity: tuple[object, ...] = metric_reference_sort_key(candidate.metric)
    else:
        identity = (
            candidate.operation.value if candidate.operation is not None else "",
            tuple(metric_reference_sort_key(item.metric) for item in candidate.operands),
        )
    return (-candidate.score, kind_order, identity, candidate.suggested_scale.value)


def _direct_candidate(
    claim: IdentifiedClaim,
    observation: MetricObservation,
    aliases: dict[str, tuple[str, ...]],
    context: str,
) -> CandidateMatch | None:
    scale, numeric_feature = _best_numeric_feature(claim, observation.value)
    features = [numeric_feature] if numeric_feature is not None else []
    features.extend(_metric_features(observation, aliases, context))
    if claim.kind is ClaimKind.DIRECT_RESULT:
        features.append(MatchFeature("kind.direct_result", 5, "Claim kind favors a direct metric"))
    elif claim.kind is ClaimKind.DERIVED_RESULT:
        features.append(
            MatchFeature("kind.derived_result", -8, "Claim kind favors a derived value")
        )
    score = _bounded_score(features)
    if score < MATCH_MINIMUM_SCORE:
        return None
    uncertainties: list[str] = ["candidate requires explicit user confirmation"]
    if numeric_feature is None:
        uncertainties.append("the current metric value does not match the displayed Claim value")
    if scale is not LinkScale.IDENTITY:
        uncertainties.append("the suggested fraction/percent conversion must be confirmed")
    return CandidateMatch(
        claim_id=claim.claim_id.value,
        suggestion_type=LinkSuggestionType.DIRECT,
        score=score,
        features=tuple(features),
        uncertainties=tuple(sorted(uncertainties)),
        suggested_scale=scale,
        metric=_metric_reference(observation, scale),
    )


def _best_numeric_feature(
    claim: IdentifiedClaim, source_value: Decimal
) -> tuple[LinkScale, MatchFeature | None]:
    best_scale = LinkScale.IDENTITY
    best_feature: MatchFeature | None = None
    expected = claim.value.canonical
    assert expected is not None
    for scale in LinkScale:
        converted = scale.apply(source_value)
        if converted == expected:
            contribution = 45 if scale is LinkScale.IDENTITY else 42
            summary = (
                "metric value exactly matches the Claim value"
                if scale is LinkScale.IDENTITY
                else f"metric value matches after explicit {scale.value} conversion"
            )
        elif _within_display_interval(claim, converted):
            contribution = 38 if scale is LinkScale.IDENTITY else 35
            summary = (
                "metric value falls within the Claim display-precision interval"
                if scale is LinkScale.IDENTITY
                else f"converted metric falls within display precision via {scale.value}"
            )
        elif _near_value(expected, converted):
            contribution = 10
            summary = f"metric value is numerically near the Claim under {scale.value}"
        else:
            continue
        feature = MatchFeature("numeric.value", contribution, summary)
        if best_feature is None or contribution > best_feature.contribution:
            best_scale, best_feature = scale, feature
    return best_scale, best_feature


def _metric_features(
    observation: MetricObservation,
    aliases: dict[str, tuple[str, ...]],
    context: str,
) -> list[MatchFeature]:
    features: list[MatchFeature] = []
    metric_phrase = _normalized_phrase(observation.metric_name)
    if metric_phrase and _contains_phrase(context, metric_phrase):
        features.append(
            MatchFeature(
                "context.metric_name", 30, f"context names metric {observation.metric_name}"
            )
        )
    else:
        matched_alias = next(
            (
                alias
                for alias in aliases.get(observation.metric_name.casefold(), ())
                if _contains_phrase(context, _normalized_phrase(alias))
            ),
            None,
        )
        if matched_alias is not None:
            features.append(
                MatchFeature(
                    "context.metric_alias",
                    26,
                    f"context alias {matched_alias!r} maps to {observation.metric_name}",
                )
            )
    for code, value, contribution in (
        ("context.run_id", observation.run_id, 8),
        ("context.dataset", observation.dataset, 6),
        ("context.split", observation.split, 6),
    ):
        phrase = _normalized_phrase(value or "")
        if phrase and _contains_phrase(context, phrase):
            features.append(MatchFeature(code, contribution, f"context contains {value!r}"))
    return features


def _derived_candidates(
    claim: IdentifiedClaim,
    catalog: ExperimentCatalog,
    aliases: dict[str, tuple[str, ...]],
    context: str,
) -> list[CandidateMatch]:
    grouped: dict[str, list[MetricObservation]] = defaultdict(list)
    for observation in catalog.observations:
        grouped[observation.metric_name].append(observation)
    candidates: list[CandidateMatch] = []
    if claim.classification.candidate.kind is NumericCandidateKind.MEAN_STD:
        for observations in grouped.values():
            candidate = _mean_candidate(claim, tuple(observations), aliases, context)
            if candidate is not None:
                candidates.append(candidate)
    if claim.kind is not ClaimKind.DERIVED_RESULT or _DERIVED_CUE_PATTERN.search(context) is None:
        return candidates
    for observations in grouped.values():
        if len(observations) > MAX_DERIVED_GROUP_SIZE:
            continue
        ordered = tuple(sorted(observations, key=_observation_identity))
        for baseline in ordered:
            for candidate_observation in ordered:
                if baseline.observation_id == candidate_observation.observation_id:
                    continue
                candidate = _pair_candidate(
                    claim,
                    baseline,
                    candidate_observation,
                    aliases,
                    context,
                )
                if candidate is not None:
                    candidates.append(candidate)
    return candidates


def _pair_candidate(
    claim: IdentifiedClaim,
    baseline: MetricObservation,
    candidate: MetricObservation,
    aliases: dict[str, tuple[str, ...]],
    context: str,
) -> CandidateMatch | None:
    if baseline.metric_name != candidate.metric_name:
        return None
    point_cue = _POINT_CUE_PATTERN.search(context) is not None
    relative_cue = _RELATIVE_CUE_PATTERN.search(context) is not None and not point_cue
    if relative_cue:
        if baseline.value == 0:
            return None
        operation = DerivedOperation.RELATIVE_CHANGE
        raw_result = (candidate.value - baseline.value) / abs(baseline.value)
        output_unit = NumericUnit.RATIO
    else:
        operation = DerivedOperation.SUBTRACTION
        raw_result = candidate.value - baseline.value
        output_unit = NumericUnit.PERCENT_POINTS if point_cue else NumericUnit.SCALAR
    comparison_result = raw_result * Decimal("100") if point_cue else raw_result
    scale, numeric_feature = _best_derived_numeric_feature(claim, comparison_result, False)
    if numeric_feature is None:
        return None
    features = [numeric_feature]
    features.extend(_metric_features(candidate, aliases, context))
    features.extend(
        (
            MatchFeature("kind.derived_result", 10, "Claim kind favors a derived operation"),
            MatchFeature(
                "context.derived_cue",
                18,
                f"context supports {operation.value}",
            ),
        )
    )
    score = _bounded_score(features)
    if score < MATCH_MINIMUM_SCORE:
        return None
    operands = (
        DerivedOperand("baseline", _metric_reference(baseline, LinkScale.IDENTITY)),
        DerivedOperand("candidate", _metric_reference(candidate, LinkScale.IDENTITY)),
    )
    return CandidateMatch(
        claim_id=claim.claim_id.value,
        suggestion_type=LinkSuggestionType.DERIVED,
        score=score,
        features=tuple(features),
        uncertainties=("derived operands and operation require explicit user confirmation",),
        suggested_scale=scale,
        operation=operation,
        operands=operands,
        output_unit=output_unit,
    )


def _best_derived_numeric_feature(
    claim: IdentifiedClaim,
    raw_result: Decimal,
    prefer_points: bool,
) -> tuple[LinkScale, MatchFeature | None]:
    scales = (
        (LinkScale.FRACTION_TO_PERCENT, LinkScale.IDENTITY, LinkScale.PERCENT_TO_FRACTION)
        if prefer_points
        else tuple(LinkScale)
    )
    for scale in scales:
        converted = scale.apply(raw_result)
        if converted == claim.value.canonical or _within_display_interval(claim, converted):
            return (
                scale,
                MatchFeature(
                    "numeric.derived_value",
                    45 if converted == claim.value.canonical else 38,
                    f"computed value matches the Claim under {scale.value}",
                ),
            )
    return LinkScale.IDENTITY, None


def _mean_candidate(
    claim: IdentifiedClaim,
    observations: tuple[MetricObservation, ...],
    aliases: dict[str, tuple[str, ...]],
    context: str,
) -> CandidateMatch | None:
    if len(observations) < 2 or len(observations) > MAX_DERIVED_GROUP_SIZE:
        return None
    ordered = tuple(sorted(observations, key=_observation_identity))
    mean = sum((item.value for item in ordered), Decimal("0")) / Decimal(len(ordered))
    scale, numeric_feature = _best_derived_numeric_feature(claim, mean, False)
    if numeric_feature is None:
        return None
    features = [numeric_feature]
    features.extend(_metric_features(ordered[0], aliases, context))
    features.append(MatchFeature("kind.mean_std", 12, "Claim is a lexical mean ± std value"))
    candidate = claim.classification.candidate
    uncertainties = [
        "the mean is linkable; the displayed ± component remains review evidence in this MVP"
    ]
    if candidate.uncertainty is not None:
        sample_std = _standard_deviation(ordered, sample=True)
        population_std = _standard_deviation(ordered, sample=False)
        for mode, value in (
            (StandardDeviationMode.SAMPLE, sample_std),
            (StandardDeviationMode.POPULATION, population_std),
        ):
            if value == candidate.uncertainty.canonical:
                features.append(
                    MatchFeature(
                        "numeric.displayed_std",
                        20,
                        f"the displayed uncertainty matches {mode.value} standard deviation",
                    )
                )
                break
    operands = tuple(
        DerivedOperand(
            f"observation_{index:03d}",
            _metric_reference(observation, LinkScale.IDENTITY),
        )
        for index, observation in enumerate(ordered)
    )
    return CandidateMatch(
        claim_id=claim.claim_id.value,
        suggestion_type=LinkSuggestionType.DERIVED,
        score=_bounded_score(features),
        features=tuple(features),
        uncertainties=tuple(sorted(uncertainties)),
        suggested_scale=scale,
        operation=DerivedOperation.MEAN,
        operands=operands,
        output_unit=claim.value.unit,
    )


def _standard_deviation(observations: tuple[MetricObservation, ...], *, sample: bool) -> Decimal:
    mean = sum((item.value for item in observations), Decimal("0")) / Decimal(len(observations))
    squared = sum(((item.value - mean) ** 2 for item in observations), Decimal("0"))
    denominator = Decimal(len(observations) - 1 if sample else len(observations))
    return (squared / denominator).sqrt()


def _metric_reference(observation: MetricObservation, scale: LinkScale) -> MetricReference:
    return MetricReference(
        source_file=observation.source_file,
        run_id=observation.run_id,
        metric_name=observation.metric_name,
        source_selector=observation.source_selector,
        scale=scale,
    )


def _within_display_interval(claim: IdentifiedClaim, value: Decimal) -> bool:
    places = claim.value.decimal_places
    if places is None:
        return False
    half_step = Decimal("0.5").scaleb(-places) * claim.value.scale
    expected = claim.value.canonical
    assert expected is not None
    return abs(value - expected) <= abs(half_step)


def _near_value(expected: Decimal, observed: Decimal) -> bool:
    difference = abs(expected - observed)
    scale = max(abs(expected), abs(observed), Decimal("1e-12"))
    return difference / scale <= Decimal("0.02")


def _aliases_by_metric(
    metric_aliases: tuple[tuple[str, tuple[str, ...]], ...],
) -> dict[str, tuple[str, ...]]:
    return {
        metric.casefold(): tuple(sorted({metric, *aliases}, key=str.casefold))
        for metric, aliases in metric_aliases
    }


def _normalized_context(claim: IdentifiedClaim) -> str:
    candidate = claim.classification.candidate
    values = (
        claim.context.summary,
        claim.context.structural_anchor,
        claim.context.table_anchor or "",
        candidate.prefix,
        candidate.suffix,
        candidate.command or "",
    )
    return " ".join(_TOKEN_PATTERN.findall(" ".join(values).casefold()))


def _normalized_phrase(value: str) -> str:
    return " ".join(_TOKEN_PATTERN.findall(value.casefold().replace("_", " ")))


def _contains_phrase(context: str, phrase: str) -> bool:
    return bool(phrase) and f" {phrase} " in f" {context} "


def _bounded_score(features: list[MatchFeature]) -> int:
    return max(0, min(100, sum(item.contribution for item in features)))


def _observation_identity(observation: MetricObservation) -> tuple[str, str, str, str]:
    return (
        observation.run_id,
        observation.metric_name,
        observation.source_file,
        observation.source_selector,
    )
