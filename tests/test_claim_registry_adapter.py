from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from pathlib import Path
from typing import cast

import pytest
import yaml

import metricproof.adapters.claim_registry as registry_adapter
from metricproof.adapters.claim_registry import YamlClaimRegistryRepository
from metricproof.adapters.config import YamlConfigurationRepository
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.application.errors import ExitCode
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.application.registry_errors import ClaimRegistryError
from metricproof.domain.claim_identity import (
    ClaimIdentitySnapshot,
    ClaimMigrationMethod,
    ClaimMigrationStatus,
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


def _claim(root: Path):
    source = root / "main.tex"
    source.write_text("Accuracy reaches 87.2\\%.", encoding="utf-8")
    scan = LocalLatexPaperScanner().scan(root, ("main.tex",))
    result = identify_claims(scan, classify_raw_candidates(scan))
    assert len(result.claims) == 1
    return result.claims[0]


def _metric(run_id: str, metric_name: str = "accuracy") -> MetricReference:
    return MetricReference(
        source_file=f"runs/{run_id}.json",
        run_id=run_id,
        metric_name=metric_name,
        source_selector=f"metrics.{metric_name}",
    )


def _identity_with_id(identity: ClaimIdentitySnapshot, value: str) -> ClaimIdentitySnapshot:
    return replace(identity, claim_id=StableClaimId(value))


def _sample_registry(root: Path) -> ClaimRegistry:
    claim = _claim(root)
    identity = ClaimIdentitySnapshot.from_claim(claim)
    direct = DirectLink(
        claim_id=identity.claim_id,
        metric=replace(_metric("direct"), scale=LinkScale.PERCENT_TO_FRACTION),
        confirmed_fingerprint=identity.fingerprint.digest,
        tolerance_override=NumericTolerance(Decimal("0.001"), Decimal("0")),
        note="confirmed direct",
    )
    active = ClaimRegistryEntry(
        identity=identity,
        status=ClaimRegistryStatus.ACTIVE,
        link=direct,
        note="active entry",
        migration=RegistryMigrationRecord(
            status=ClaimMigrationStatus.EXACT,
            method=ClaimMigrationMethod.STABLE_ID,
            score=100,
            previous_path="main.tex",
            current_path="main.tex",
            evidence=("stable ID matches",),
        ),
    )

    derived_id = StableClaimId("clm_" + "d" * 20)
    derived_identity = _identity_with_id(identity, derived_id.value)
    derived = DerivedLink(
        claim_id=derived_id,
        operation=DerivedOperation.STANDARD_DEVIATION,
        operands=(
            DerivedOperand("seed_1", _metric("seed-1")),
            DerivedOperand("seed_2", _metric("seed-2")),
        ),
        output_unit=NumericUnit.SCALAR,
        output_scale=LinkScale.IDENTITY,
        confirmed_fingerprint=identity.fingerprint.digest,
        rounding=RoundingPolicy(decimal_places=3),
        standard_deviation_mode=StandardDeviationMode.SAMPLE,
        note="sample standard deviation",
    )
    derived_entry = ClaimRegistryEntry(
        identity=derived_identity,
        status=ClaimRegistryStatus.BROKEN,
        link=derived,
    )

    ignored_id = StableClaimId("clm_" + "e" * 20)
    ignored_entry = ClaimRegistryEntry(
        identity=_identity_with_id(identity, ignored_id.value),
        status=ClaimRegistryStatus.IGNORED,
        ignore=IgnoreRecord(IgnoreReason.NON_EXPERIMENTAL_NUMBER, "publication year"),
    )
    return ClaimRegistry(
        entries=tuple(
            sorted((active, derived_entry, ignored_entry), key=lambda item: item.claim_id)
        )
    )


def test_missing_registry_is_empty_even_when_parent_is_absent(tmp_path: Path) -> None:
    repository = YamlClaimRegistryRepository()

    registry = repository.load(tmp_path, ".metricproof/claims.yml")

    assert registry == ClaimRegistry()
    assert not (tmp_path / ".metricproof").exists()


def test_registry_round_trip_is_strict_readable_and_byte_stable(tmp_path: Path) -> None:
    (tmp_path / ".metricproof").mkdir()
    repository = YamlClaimRegistryRepository()
    registry = _sample_registry(tmp_path)

    repository.save(tmp_path, ".metricproof/claims.yml", registry)
    path = tmp_path / ".metricproof" / "claims.yml"
    first = path.read_bytes()
    loaded = repository.load(tmp_path, ".metricproof/claims.yml")
    repository.save(tmp_path, ".metricproof/claims.yml", loaded)

    assert loaded == registry
    assert path.read_bytes() == first
    text = first.decode("utf-8")
    assert text.startswith("schema_version: '1'\nclaims:\n")
    assert "type: direct" in text
    assert "type: derived" in text
    assert "standard_deviation_mode: sample" in text
    assert str(tmp_path) not in text


def test_two_hundred_registry_entries_round_trip_in_stable_order(tmp_path: Path) -> None:
    (tmp_path / ".metricproof").mkdir()
    repository = YamlClaimRegistryRepository()
    claim = _claim(tmp_path)
    base_identity = ClaimIdentitySnapshot.from_claim(claim)
    entries: list[ClaimRegistryEntry] = []
    for index in range(200):
        digest = sha256(f"generated-{index}".encode()).hexdigest()[:20]
        claim_id = StableClaimId(f"clm_{digest}")
        identity = replace(base_identity, claim_id=claim_id)
        entries.append(
            ClaimRegistryEntry(
                identity=identity,
                status=ClaimRegistryStatus.ACTIVE,
                link=DirectLink(
                    claim_id=claim_id,
                    metric=_metric(f"run-{index:03d}"),
                    confirmed_fingerprint=identity.fingerprint.digest,
                ),
            )
        )
    registry = ClaimRegistry(entries=tuple(sorted(entries, key=lambda item: item.claim_id)))

    repository.save(tmp_path, ".metricproof/claims.yml", registry)
    loaded = repository.load(tmp_path, ".metricproof/claims.yml")

    assert loaded == registry
    assert tuple(entry.claim_id for entry in loaded.entries) == tuple(
        sorted(entry.claim_id for entry in loaded.entries)
    )


@pytest.mark.parametrize(
    ("body", "fragment"),
    [
        ("schema_version: '2'\nclaims: []\n", "unsupported schema"),
        ("schema_version: '1'\nclaims: [\n", "invalid safe YAML"),
        ("!!python/object/apply:os.system ['echo unsafe']\n", "invalid safe YAML"),
        ("schema_version: '1'\nunknown: true\nclaims: []\n", "unknown"),
        ("schema_version: '1'\nclaims: wrong\n", "valid list"),
    ],
)
def test_registry_rejects_schema_yaml_unsafe_unknown_and_wrong_types(
    tmp_path: Path, body: str, fragment: str
) -> None:
    marker = tmp_path / ".metricproof"
    marker.mkdir()
    (marker / "claims.yml").write_text(body, encoding="utf-8")

    with pytest.raises(ClaimRegistryError, match=fragment):
        YamlClaimRegistryRepository().load(tmp_path, ".metricproof/claims.yml")


def test_registry_rejects_duplicate_ids_and_invalid_link_values(tmp_path: Path) -> None:
    marker = tmp_path / ".metricproof"
    marker.mkdir()
    repository = YamlClaimRegistryRepository()
    registry = _sample_registry(tmp_path)
    repository.save(tmp_path, ".metricproof/claims.yml", registry)
    path = marker / "claims.yml"
    parsed = cast(dict[str, object], yaml.safe_load(path.read_text(encoding="utf-8")))
    claims = cast(list[object], parsed["claims"])
    assert claims
    claims.append(claims[0])
    path.write_text(yaml.safe_dump(parsed, sort_keys=False), encoding="utf-8")

    with pytest.raises(ClaimRegistryError, match="duplicate Claim IDs"):
        repository.load(tmp_path, ".metricproof/claims.yml")

    repository.save(tmp_path, ".metricproof/claims.yml", registry)
    text = path.read_text(encoding="utf-8").replace("scale: percent_to_fraction", "scale: auto")
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ClaimRegistryError, match="scale"):
        repository.load(tmp_path, ".metricproof/claims.yml")


def test_atomic_write_failure_preserves_prior_registry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / ".metricproof"
    marker.mkdir()
    repository = YamlClaimRegistryRepository()
    registry = _sample_registry(tmp_path)
    repository.save(tmp_path, ".metricproof/claims.yml", registry)
    path = marker / "claims.yml"
    before = path.read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        assert source.parent == destination.parent
        raise PermissionError("simulated replace denial")

    monkeypatch.setattr(registry_adapter.os, "replace", fail_replace)
    with pytest.raises(ClaimRegistryError) as captured:
        repository.save(
            tmp_path,
            ".metricproof/claims.yml",
            registry.with_entry(replace(registry.entries[0], status=ClaimRegistryStatus.BROKEN)),
        )

    assert captured.value.exit_code is ExitCode.ENVIRONMENT_ERROR
    assert path.read_bytes() == before
    assert list(marker.glob(".claims.yml.*.tmp")) == []


@pytest.mark.parametrize(
    "registry_path",
    ["", "../claims.yml", "C:/claims.yml", "C:\\claims.yml", "claims.json"],
)
def test_registry_paths_stay_inside_project(tmp_path: Path, registry_path: str) -> None:
    repository = YamlClaimRegistryRepository()
    with pytest.raises(ClaimRegistryError, match="project-relative POSIX"):
        repository.load(tmp_path, registry_path)


def test_save_requires_existing_project_local_parent(tmp_path: Path) -> None:
    repository = YamlClaimRegistryRepository()
    with pytest.raises(ClaimRegistryError, match="parent directory"):
        repository.save(tmp_path, "missing/claims.yml", ClaimRegistry())


def test_configuration_loads_and_validates_claim_registry_path(tmp_path: Path) -> None:
    marker = tmp_path / ".metricproof"
    marker.mkdir()
    (tmp_path / "main.tex").write_text("Accuracy 1.", encoding="utf-8")
    (marker / "config.yml").write_text(
        "schema_version: '1'\npaper_paths: [main.tex]\nclaim_registry_path: registry/custom.yaml\n",
        encoding="utf-8",
    )

    configuration = YamlConfigurationRepository().load(tmp_path)

    assert configuration.claim_registry_path == "registry/custom.yaml"


@pytest.mark.parametrize("value", ["../claims.yml", "C:/claims.yml", "claims/*.yml", "claims.json"])
def test_configuration_rejects_unsafe_registry_paths(tmp_path: Path, value: str) -> None:
    marker = tmp_path / ".metricproof"
    marker.mkdir()
    (marker / "config.yml").write_text(
        f"schema_version: '1'\nclaim_registry_path: {value!r}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigurationError, match="claim_registry_path"):
        YamlConfigurationRepository().load(tmp_path)
