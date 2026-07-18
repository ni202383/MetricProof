from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.application.claim_registry import (
    load_claim_registry,
    save_claim_registry,
    save_registry_entry,
)
from metricproof.domain.claim_identity import (
    ClaimIdentitySnapshot,
    ClaimMigrationMethod,
    ClaimMigrationStatus,
    IdentifiedClaim,
    StableClaimId,
    identify_claims,
)
from metricproof.domain.claims import classify_raw_candidates
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
from metricproof.domain.models import NumericUnit
from metricproof.domain.registry import (
    ClaimRegistry,
    ClaimRegistryEntry,
    ClaimRegistryStatus,
    IgnoreReason,
    IgnoreRecord,
    RegistryMigrationRecord,
)


def _identified_claim(root: Path) -> IdentifiedClaim:
    source = root / "main.tex"
    source.write_text("Accuracy reaches 87.2\\%.", encoding="utf-8")
    scan = LocalLatexPaperScanner().scan(root, ("main.tex",))
    identities = identify_claims(scan, classify_raw_candidates(scan))
    assert len(identities.claims) == 1
    return identities.claims[0]


def _metric(
    *,
    source_file: str = "runs/result.json",
    run_id: str = "run-a",
    metric_name: str = "accuracy",
    selector: str = "metrics.accuracy",
    scale: LinkScale = LinkScale.IDENTITY,
) -> MetricReference:
    return MetricReference(source_file, run_id, metric_name, selector, scale)


def _direct(claim: IdentifiedClaim) -> DirectLink:
    return DirectLink(
        claim_id=claim.claim_id,
        metric=_metric(),
        confirmed_fingerprint=claim.fingerprint.digest,
    )


@pytest.mark.parametrize(
    ("scale", "value", "expected"),
    [
        (LinkScale.IDENTITY, "0.872", "0.872"),
        (LinkScale.FRACTION_TO_PERCENT, "0.872", "87.200"),
        (LinkScale.PERCENT_TO_FRACTION, "87.2", "0.872"),
    ],
)
def test_link_scales_are_explicit_decimal_conversions(
    scale: LinkScale, value: str, expected: str
) -> None:
    assert scale.apply(Decimal(value)) == Decimal(expected)
    with pytest.raises(ValueError, match="finite"):
        scale.apply(Decimal("NaN"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"absolute": Decimal("-1")},
        {"relative": Decimal("-1")},
        {"absolute": Decimal("Infinity")},
        {"relative": Decimal("NaN")},
    ],
)
def test_numeric_tolerance_rejects_negative_or_non_finite_values(
    kwargs: dict[str, Decimal],
) -> None:
    with pytest.raises(ValueError, match="tolerances"):
        NumericTolerance(**kwargs)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"source_file": "C:/result.json"}, "project-relative"),
        ({"source_file": "../result.json"}, "project-relative"),
        ({"source_file": "runs\\result.json"}, "project-relative"),
        ({"run_id": ""}, "run_id"),
        ({"metric_name": " "}, "metric_name"),
        ({"source_selector": ""}, "source_selector"),
    ],
)
def test_metric_reference_rejects_unsafe_or_incomplete_values(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        replace(_metric(), **changes)


def test_direct_link_and_rounding_policy_are_strict(tmp_path: Path) -> None:
    claim = _identified_claim(tmp_path)
    link = _direct(claim)
    assert link.metric.scale is LinkScale.IDENTITY

    with pytest.raises(ValueError, match="confirmed_fingerprint"):
        replace(link, confirmed_fingerprint="not-a-digest")
    with pytest.raises(ValueError, match="non-negative"):
        RoundingPolicy(decimal_places=-1)
    policy = RoundingPolicy(decimal_places=2)
    assert policy.apply(Decimal("1.235")) == Decimal("1.24")
    assert RoundingPolicy().apply(Decimal("1.235")) == Decimal("1.235")
    with pytest.raises(ValueError, match="finite"):
        policy.apply(Decimal("NaN"))


def test_derived_link_supports_only_bounded_single_layer_operations(tmp_path: Path) -> None:
    claim = _identified_claim(tmp_path)
    baseline = DerivedOperand("baseline", _metric(run_id="baseline"))
    candidate = DerivedOperand("candidate", _metric(run_id="candidate"))
    operands = (baseline, candidate)

    subtraction = DerivedLink(
        claim_id=claim.claim_id,
        operation=DerivedOperation.SUBTRACTION,
        operands=operands,
        output_unit=NumericUnit.PERCENT_POINTS,
        output_scale=LinkScale.FRACTION_TO_PERCENT,
        confirmed_fingerprint=claim.fingerprint.digest,
    )
    relative = replace(subtraction, operation=DerivedOperation.RELATIVE_CHANGE)
    mean = replace(
        subtraction,
        operation=DerivedOperation.MEAN,
        operands=(DerivedOperand("seed_1", _metric(run_id="seed-1")),),
        output_unit=NumericUnit.SCALAR,
        output_scale=LinkScale.IDENTITY,
    )
    standard_deviation = replace(
        mean,
        operation=DerivedOperation.STANDARD_DEVIATION,
        operands=(
            DerivedOperand("seed_1", _metric(run_id="seed-1")),
            DerivedOperand("seed_2", _metric(run_id="seed-2")),
        ),
        standard_deviation_mode=StandardDeviationMode.SAMPLE,
    )

    assert subtraction.operation is DerivedOperation.SUBTRACTION
    assert relative.operation is DerivedOperation.RELATIVE_CHANGE
    assert mean.operation is DerivedOperation.MEAN
    assert standard_deviation.standard_deviation_mode is StandardDeviationMode.SAMPLE

    invalid: tuple[tuple[dict[str, object], str], ...] = (
        ({"operands": (candidate, baseline)}, "stable ordering"),
        ({"operands": (baseline,)}, "baseline and candidate"),
        ({"operation": DerivedOperation.MEAN, "operands": ()}, "at least one"),
        (
            {
                "operation": DerivedOperation.STANDARD_DEVIATION,
                "operands": (baseline,),
            },
            "at least two",
        ),
        (
            {
                "operation": DerivedOperation.STANDARD_DEVIATION,
                "operands": operands,
            },
            "sample or population",
        ),
        ({"standard_deviation_mode": StandardDeviationMode.POPULATION}, "only valid"),
    )
    for changes, message in invalid:
        with pytest.raises(ValueError, match=message):
            replace(subtraction, **changes)

    with pytest.raises(ValueError, match="snake_case"):
        DerivedOperand("Seed 1", _metric())


def test_registry_entry_status_and_decision_invariants(tmp_path: Path) -> None:
    claim = _identified_claim(tmp_path)
    identity = ClaimIdentitySnapshot.from_claim(claim)
    link = _direct(claim)
    ignore = IgnoreRecord(IgnoreReason.NON_EXPERIMENTAL_NUMBER, "manual review")
    active = ClaimRegistryEntry(identity, ClaimRegistryStatus.ACTIVE, link=link)
    ignored = ClaimRegistryEntry(identity, ClaimRegistryStatus.IGNORED, ignore=ignore)
    broken = ClaimRegistryEntry(identity, ClaimRegistryStatus.BROKEN, link=link)

    assert active.direct_link == link
    assert ignored.direct_link is None
    assert broken.link == link
    with pytest.raises(ValueError, match="exactly one"):
        ClaimRegistryEntry(identity, ClaimRegistryStatus.ACTIVE)
    with pytest.raises(ValueError, match="exactly one"):
        ClaimRegistryEntry(identity, ClaimRegistryStatus.ACTIVE, link=link, ignore=ignore)
    with pytest.raises(ValueError, match="active"):
        ClaimRegistryEntry(identity, ClaimRegistryStatus.ACTIVE, ignore=ignore)
    with pytest.raises(ValueError, match="ignored"):
        ClaimRegistryEntry(identity, ClaimRegistryStatus.IGNORED, link=link)
    with pytest.raises(ValueError, match="broken"):
        ClaimRegistryEntry(identity, ClaimRegistryStatus.BROKEN, ignore=ignore)
    with pytest.raises(ValueError, match="must match"):
        ClaimRegistryEntry(
            identity,
            ClaimRegistryStatus.ACTIVE,
            link=replace(link, claim_id=StableClaimId("clm_" + "f" * 20)),
        )


def test_registry_is_versioned_unique_sorted_and_replaceable(tmp_path: Path) -> None:
    claim = _identified_claim(tmp_path)
    first = ClaimRegistryEntry(
        ClaimIdentitySnapshot.from_claim(claim),
        ClaimRegistryStatus.ACTIVE,
        link=_direct(claim),
    )
    second_id = StableClaimId("clm_" + "f" * 20)
    second_identity = replace(first.identity, claim_id=second_id)
    second = ClaimRegistryEntry(
        second_identity,
        ClaimRegistryStatus.IGNORED,
        ignore=IgnoreRecord(IgnoreReason.OUT_OF_SCOPE),
    )

    registry = ClaimRegistry(entries=tuple(sorted((first, second), key=lambda item: item.claim_id)))
    assert registry.get(first.claim_id) == first
    assert registry.get("clm_" + "0" * 20) is None
    updated = registry.with_entry(replace(first, status=ClaimRegistryStatus.BROKEN))
    assert updated.get(first.claim_id) is not None
    assert updated.get(first.claim_id).status is ClaimRegistryStatus.BROKEN  # type: ignore[union-attr]

    with pytest.raises(ValueError, match="unsupported"):
        ClaimRegistry(schema_version="2")
    with pytest.raises(ValueError, match="stable Claim ID ordering"):
        ClaimRegistry(entries=(second, first))
    with pytest.raises(ValueError, match="duplicate"):
        ClaimRegistry(entries=(first, first))


def test_registry_migration_record_is_bounded_and_sorted() -> None:
    record = RegistryMigrationRecord(
        status=ClaimMigrationStatus.MIGRATED,
        method=ClaimMigrationMethod.VERSIONED_CONTEXT,
        score=85,
        previous_path="old.tex",
        current_path="new.tex",
        evidence=("context matches",),
    )
    assert record.score == 85
    with pytest.raises(ValueError, match="between 0 and 100"):
        replace(record, score=-1)
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(record, conflicts=("z", "a", "a"))


class _MemoryRegistryRepository:
    def __init__(self, registry: ClaimRegistry) -> None:
        self.registry = registry
        self.saved: list[ClaimRegistry] = []

    def load(self, project_root: Path, registry_path: str) -> ClaimRegistry:
        assert project_root.is_absolute()
        assert registry_path.endswith("claims.yml")
        return self.registry

    def save(self, project_root: Path, registry_path: str, registry: ClaimRegistry) -> None:
        assert project_root.is_absolute()
        assert registry_path.endswith("claims.yml")
        self.registry = registry
        self.saved.append(registry)


def test_registry_application_services_write_once_after_domain_update(tmp_path: Path) -> None:
    root = tmp_path.resolve()
    claim = _identified_claim(root)
    entry = ClaimRegistryEntry(
        ClaimIdentitySnapshot.from_claim(claim),
        ClaimRegistryStatus.ACTIVE,
        link=_direct(claim),
    )
    repository = _MemoryRegistryRepository(ClaimRegistry())

    assert load_claim_registry(root, ".metricproof/claims.yml", repository).entries == ()
    updated = save_registry_entry(
        root,
        ".metricproof/claims.yml",
        repository.registry,
        entry,
        repository,
    )
    save_claim_registry(root, ".metricproof/claims.yml", updated, repository)

    assert updated.entries == (entry,)
    assert repository.saved == [updated, updated]
