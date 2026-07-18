"""Explainable deterministic Claim-to-metric matching tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.application.claim_identity import prepare_claim_identities
from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.matching import suggest_links, suggest_links_for_claim
from metricproof.domain.claim_identity import IdentifiedClaim
from metricproof.domain.links import DerivedOperation, LinkScale
from metricproof.domain.matching import LinkSuggestionType
from metricproof.domain.models import (
    ExperimentCatalog,
    ExperimentRun,
    MetricObservation,
    NumericValue,
    SourceLocation,
    observation_sort_key,
)


def _configuration(*aliases: tuple[str, tuple[str, ...]]) -> ProjectConfiguration:
    return ProjectConfiguration(
        schema_version="1",
        sources=(),
        paper_paths=("main.tex",),
        metric_aliases=tuple(sorted(aliases)),
    )


def _claims(
    root: Path,
    text: str,
    configuration: ProjectConfiguration,
) -> tuple[IdentifiedClaim, ...]:
    (root / "main.tex").write_text(text, encoding="utf-8")
    scan = LocalLatexPaperScanner().scan(root, configuration.paper_paths)
    return prepare_claim_identities(scan, configuration).identities.claims


def _observation(
    run_id: str,
    metric: str,
    value: str,
    *,
    dataset: str | None = None,
    split: str | None = None,
) -> MetricObservation:
    source = f"runs/{run_id}.json"
    selector = f"metrics.{metric}"
    return MetricObservation.create(
        run_id=run_id,
        metric_name=metric,
        numeric=NumericValue(raw_text=value, parsed=Decimal(value)),
        source_file=source,
        source_selector=selector,
        location=SourceLocation(source, selector=selector),
        dataset=dataset,
        split=split,
    )


def _catalog(*observations: MetricObservation) -> ExperimentCatalog:
    ordered = tuple(sorted(observations, key=observation_sort_key))
    runs = tuple(
        ExperimentRun(
            run_id=run_id,
            observations=tuple(item for item in ordered if item.run_id == run_id),
            metadata=(),
            result_sources=tuple(
                sorted({item.source_file for item in ordered if item.run_id == run_id})
            ),
        )
        for run_id in sorted({item.run_id for item in ordered})
    )
    return ExperimentCatalog(runs=runs, observations=ordered, diagnostics=())


def test_unique_direct_candidate_explains_numeric_and_alias_evidence(tmp_path: Path) -> None:
    configuration = _configuration(("accuracy", ("top one",)))
    claim = _claims(tmp_path, "Top one reaches 0.872.", configuration)[0]
    catalog = _catalog(
        _observation("proposed", "accuracy", "0.872"),
        _observation("proposed", "loss", "0.872"),
    )

    result = suggest_links_for_claim(claim, catalog, configuration)

    assert not result.ambiguous
    assert result.candidates[0].suggestion_type is LinkSuggestionType.DIRECT
    assert result.candidates[0].metric is not None
    assert result.candidates[0].metric.metric_name == "accuracy"
    assert result.candidates[0].suggested_scale is LinkScale.IDENTITY
    assert {feature.code for feature in result.candidates[0].features} >= {
        "numeric.value",
        "context.metric_alias",
    }
    assert all("confirm" in item for item in result.candidates[0].uncertainties)


def test_same_value_multiple_metrics_is_explicitly_ambiguous(tmp_path: Path) -> None:
    configuration = _configuration(("accuracy", ("metric",)), ("f1", ("metric",)))
    claim = _claims(tmp_path, "The metric reaches 0.91.", configuration)[0]
    catalog = _catalog(
        _observation("run", "accuracy", "0.91"),
        _observation("run", "f1", "0.91"),
    )

    result = suggest_links_for_claim(claim, catalog, configuration)

    assert result.ambiguous
    assert result.candidates[0].score == result.candidates[1].score
    assert "too close" in result.uncertainties[0]


def test_fraction_and_percent_conversion_is_suggested_but_flagged(tmp_path: Path) -> None:
    configuration = _configuration(("accuracy", ()))
    claim = _claims(tmp_path, r"Accuracy reaches 87.2\%.", configuration)[0]

    result = suggest_links_for_claim(
        claim,
        _catalog(_observation("run", "accuracy", "87.2")),
        configuration,
    )

    candidate = result.candidates[0]
    assert candidate.suggested_scale is LinkScale.PERCENT_TO_FRACTION
    assert any("conversion" in item for item in candidate.uncertainties)


def test_dataset_split_and_run_context_contribute_without_deciding_alone(
    tmp_path: Path,
) -> None:
    configuration = _configuration(("accuracy", ()))
    claim = _claims(
        tmp_path,
        "Proposed accuracy on cifar10 test reaches 0.90.",
        configuration,
    )[0]
    catalog = _catalog(
        _observation("proposed", "accuracy", "0.90", dataset="cifar10", split="test")
    )

    result = suggest_links_for_claim(claim, catalog, configuration)

    codes = {feature.code for feature in result.candidates[0].features}
    assert {"context.run_id", "context.dataset", "context.split"} <= codes


def test_unrelated_metric_produces_no_candidate(tmp_path: Path) -> None:
    configuration = _configuration()
    claim = _claims(tmp_path, "The experiment uses 100 epochs.", configuration)[0]

    result = suggest_links_for_claim(
        claim,
        _catalog(_observation("run", "latency", "4.2")),
        configuration,
    )

    assert result.candidates == ()
    assert "no candidate" in result.uncertainties[0]


def test_clear_subtraction_candidate_uses_named_operands(tmp_path: Path) -> None:
    configuration = _configuration(("accuracy", ()))
    claims = _claims(
        tmp_path,
        "Accuracy improves from 0.70 to 0.80, an improvement of 0.10.",
        configuration,
    )
    claim = next(item for item in claims if item.raw_text == "0.10")
    catalog = _catalog(
        _observation("baseline", "accuracy", "0.70"),
        _observation("proposed", "accuracy", "0.80"),
    )

    result = suggest_links_for_claim(claim, catalog, configuration)
    derived = next(
        item for item in result.candidates if item.suggestion_type is LinkSuggestionType.DERIVED
    )

    assert derived.operation is DerivedOperation.SUBTRACTION
    assert tuple(item.name for item in derived.operands) == ("baseline", "candidate")
    assert derived.operands[0].metric.run_id == "baseline"
    assert derived.operands[1].metric.run_id == "proposed"


def test_relative_change_candidate_is_distinct_from_percentage_points(tmp_path: Path) -> None:
    configuration = _configuration(("accuracy", ()))
    claim = _claims(
        tmp_path,
        r"Accuracy has a relative improvement of 10\%.",
        configuration,
    )[0]
    catalog = _catalog(
        _observation("baseline", "accuracy", "0.50"),
        _observation("proposed", "accuracy", "0.55"),
    )

    result = suggest_links_for_claim(claim, catalog, configuration)
    derived = next(
        item for item in result.candidates if item.suggestion_type is LinkSuggestionType.DERIVED
    )

    assert derived.operation is DerivedOperation.RELATIVE_CHANGE
    assert derived.suggested_scale is LinkScale.IDENTITY


def test_mean_std_candidate_uses_all_seed_observations_and_keeps_uncertainty(
    tmp_path: Path,
) -> None:
    configuration = _configuration(("accuracy", ()))
    claim = _claims(tmp_path, "Accuracy is 0.9 ± 0.1.", configuration)[0]
    catalog = _catalog(
        _observation("seed-1", "accuracy", "0.8"),
        _observation("seed-2", "accuracy", "1.0"),
    )

    result = suggest_links_for_claim(claim, catalog, configuration)
    derived = next(
        item for item in result.candidates if item.suggestion_type is LinkSuggestionType.DERIVED
    )

    assert derived.operation is DerivedOperation.MEAN
    assert len(derived.operands) == 2
    assert any(feature.code == "numeric.displayed_std" for feature in derived.features)
    assert any("± component" in item for item in derived.uncertainties)


def test_ambiguous_derived_pairs_are_never_selected_automatically(tmp_path: Path) -> None:
    configuration = _configuration(("accuracy", ()))
    claim = next(
        item
        for item in _claims(
            tmp_path,
            "Accuracy reports an improvement of 0.10.",
            configuration,
        )
        if item.raw_text == "0.10"
    )
    catalog = _catalog(
        _observation("a", "accuracy", "0.70"),
        _observation("b", "accuracy", "0.80"),
        _observation("c", "accuracy", "0.90"),
    )

    result = suggest_links_for_claim(claim, catalog, configuration)

    assert result.ambiguous
    assert (
        len(
            [
                item
                for item in result.candidates
                if item.suggestion_type is LinkSuggestionType.DERIVED
            ]
        )
        >= 2
    )


def test_two_hundred_metric_claims_have_stable_unique_top_candidates(tmp_path: Path) -> None:
    def metric_name(index: int) -> str:
        return f"metric{chr(97 + index // 26)}{chr(97 + index % 26)}"

    aliases = tuple((metric_name(index), ()) for index in range(200))
    configuration = _configuration(*aliases)
    paper = "\n".join(f"{metric_name(index)} reaches {index + 1}.125." for index in range(200))
    claims = _claims(tmp_path, paper, configuration)
    catalog = _catalog(
        *(_observation("run", metric_name(index), f"{index + 1}.125") for index in range(200))
    )

    first = suggest_links(claims, catalog, configuration)
    second = suggest_links(claims, catalog, configuration)

    assert first == second
    assert len(first) == 200
    assert all(not result.ambiguous for result in first)
    assert [
        result.candidates[0].metric.metric_name for result in first if result.candidates[0].metric
    ] == [metric_name(index) for index in range(200)]
