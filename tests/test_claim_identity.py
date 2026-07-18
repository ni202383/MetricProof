from __future__ import annotations

from pathlib import Path

import pytest

import metricproof.domain.claim_identity as identity_module
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.application.claim_identity import prepare_claim_identities
from metricproof.application.configuration import ProjectConfiguration
from metricproof.domain.claim_identity import (
    FINGERPRINT_VERSION,
    ClaimIdentityResult,
    ClaimIdentitySnapshot,
    ClaimMigrationStatus,
    IdentifiedClaim,
    StableClaimId,
    identify_claims,
    migrate_claims,
)
from metricproof.domain.claims import ClaimDisposition, classify_raw_candidates


def _identify_files(
    root: Path,
    files: dict[str, str],
    *,
    include_ambiguous: bool = False,
):
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    entries = tuple(sorted(files))
    scan = LocalLatexPaperScanner().scan(root, entries)
    classifications = classify_raw_candidates(scan)
    identities = identify_claims(
        scan,
        classifications,
        include_ambiguous=include_ambiguous,
    )
    return scan, classifications, identities


def _only_claim(root: Path, text: str, *, path: str = "main.tex"):
    _, _, identities = _identify_files(root, {path: text})
    assert len(identities.claims) == 1
    return identities.claims[0]


def test_same_input_has_same_versioned_opaque_identity(tmp_path: Path) -> None:
    text = "Accuracy reaches 87.2\\%."
    first = _only_claim(tmp_path, text)
    second = _only_claim(tmp_path, text)

    assert first.claim_id == second.claim_id
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint.version == FINGERPRINT_VERSION
    assert first.claim_id.value.startswith("clm_")
    assert len(first.claim_id.value) == 24
    assert str(tmp_path) not in first.claim_id.value
    assert "87.2" not in first.claim_id.value
    assert all(str(tmp_path) not in value for _, value in first.fingerprint.components)


def test_numeric_change_retains_identity_but_changes_semantic_digest(tmp_path: Path) -> None:
    before = _only_claim(tmp_path, "Accuracy reaches 87.2\\%.")
    after = _only_claim(tmp_path, "Accuracy reaches 88.4\\%.")

    assert after.claim_id == before.claim_id
    assert after.fingerprint.digest == before.fingerprint.digest
    assert after.fingerprint.context_digest == before.fingerprint.context_digest
    assert after.fingerprint.semantic_digest != before.fingerprint.semantic_digest
    migration = migrate_claims((ClaimIdentitySnapshot.from_claim(before),), _identity_result(after))
    assert migration[0].status is ClaimMigrationStatus.EXACT
    assert migration[0].resolved_claim is not None
    assert migration[0].resolved_claim.claim_id == before.claim_id


def test_line_and_small_text_insertions_migrate_to_the_persistent_id(tmp_path: Path) -> None:
    before = _only_claim(tmp_path, "Accuracy reaches 87.2\\%.")
    after = _only_claim(
        tmp_path,
        "A short reproducibility note was added.\nAccuracy now reaches 87.2\\%.",
    )

    assert after.claim_id != before.claim_id
    migration = migrate_claims((ClaimIdentitySnapshot.from_claim(before),), _identity_result(after))
    result = migration[0]
    assert result.status is ClaimMigrationStatus.MIGRATED
    assert result.score >= 70
    assert result.resolved_claim is not None
    assert result.resolved_claim.claim_id == before.claim_id
    assert result.generated_claim_id == after.claim_id
    assert result.old_location != result.new_location
    assert result.evidence


def test_trailing_line_insertion_retains_the_persistent_claim_id(tmp_path: Path) -> None:
    before = _only_claim(tmp_path, "Accuracy reaches 87.2\\%.")
    after = _only_claim(
        tmp_path,
        "Accuracy reaches 87.2\\%.\nA short reproducibility appendix was added.",
    )

    migration = migrate_claims((ClaimIdentitySnapshot.from_claim(before),), _identity_result(after))

    assert migration[0].status in {ClaimMigrationStatus.EXACT, ClaimMigrationStatus.MIGRATED}
    assert migration[0].resolved_claim is not None
    assert migration[0].resolved_claim.claim_id == before.claim_id


def test_two_hundred_ordinary_prefix_insertions_migrate_deterministically(tmp_path: Path) -> None:
    before = _only_claim(tmp_path, "Accuracy reaches 87.2\\%.")
    snapshot = ClaimIdentitySnapshot.from_claim(before)

    for index in range(200):
        inserted = "x" * (index % 40)
        after = _only_claim(
            tmp_path,
            f"Editorial note {inserted}.\nAccuracy reaches 87.2\\%.",
        )
        first = migrate_claims((snapshot,), _identity_result(after))[0]
        second = migrate_claims((snapshot,), _identity_result(after))[0]
        assert first == second
        assert first.status in {ClaimMigrationStatus.EXACT, ClaimMigrationStatus.MIGRATED}
        assert first.resolved_claim is not None
        assert first.resolved_claim.claim_id == before.claim_id


def test_unique_file_rename_uses_context_but_repeated_content_is_ambiguous(
    tmp_path: Path,
) -> None:
    before = _only_claim(tmp_path, "Accuracy reaches 87.2\\%.", path="paper/old.tex")
    renamed = _only_claim(tmp_path, "Accuracy reaches 87.2\\%.", path="paper/new.tex")
    rename_result = migrate_claims(
        (ClaimIdentitySnapshot.from_claim(before),), _identity_result(renamed)
    )[0]

    assert rename_result.status is ClaimMigrationStatus.MIGRATED
    assert rename_result.resolved_claim is not None
    assert rename_result.resolved_claim.claim_id == before.claim_id

    _, _, duplicated = _identify_files(
        tmp_path,
        {"paper/new.tex": ("Accuracy reaches 87.2\\%.\nAccuracy reaches 87.2\\%.\n")},
    )
    duplicate_result = migrate_claims((ClaimIdentitySnapshot.from_claim(renamed),), duplicated)[0]
    assert duplicate_result.status is ClaimMigrationStatus.AMBIGUOUS
    assert duplicate_result.resolved_claim is None
    assert len(duplicate_result.conflicts) == 2


def test_missing_and_one_to_one_collision_are_explicit(tmp_path: Path) -> None:
    _, _, old = _identify_files(
        tmp_path,
        {
            "old/a.tex": "Accuracy reaches 87.2\\%.",
            "old/b.tex": "Accuracy reaches 87.2\\%.",
        },
    )
    snapshots = tuple(ClaimIdentitySnapshot.from_claim(claim) for claim in old.claims)
    _, _, current = _identify_files(
        tmp_path,
        {"new/only.tex": "Accuracy reaches 87.2\\%."},
    )

    collision_results = migrate_claims(snapshots, current)
    assert {item.status for item in collision_results} == {ClaimMigrationStatus.COLLISION}
    assert all(item.resolved_claim is None for item in collision_results)

    _, _, unrelated = _identify_files(
        tmp_path,
        {"other.tex": "Training uses 100 epochs."},
    )
    missing = migrate_claims((snapshots[0],), unrelated)[0]
    assert missing.status is ClaimMigrationStatus.MISSING
    assert missing.resolved_claim is None


def test_digest_collision_is_reported_without_silent_overwrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def colliding_digest(components: tuple[tuple[str, str], ...]) -> str:
        assert components
        return "0" * 64

    monkeypatch.setattr(identity_module, "_stable_digest", colliding_digest)
    _, _, identities = _identify_files(
        tmp_path,
        {"main.tex": "Accuracy reaches 87.2\\%. F1 score reaches 0.913."},
    )

    assert len(identities.claims) == 2
    assert identities.claims[0].claim_id == StableClaimId("clm_00000000000000000000")
    assert len(identities.collisions) == 1
    assert identities.collisions[0].locations == tuple(
        sorted(claim.location for claim in identities.claims)
    )


def test_identity_scope_excludes_non_experiment_and_requires_explicit_ambiguous(
    tmp_path: Path,
) -> None:
    scan, classifications, default = _identify_files(
        tmp_path,
        {"main.tex": "See Figure 2. A bare value is 0.5."},
    )
    dispositions = {item.disposition for item in classifications.classifications}
    assert ClaimDisposition.NON_EXPERIMENT in dispositions
    assert ClaimDisposition.AMBIGUOUS in dispositions
    assert default.claims == ()

    explicit = identify_claims(scan, classifications, include_ambiguous=True)
    assert len(explicit.claims) == 1
    assert explicit.claims[0].disposition is ClaimDisposition.AMBIGUOUS


def test_table_identity_uses_label_and_logical_cell_position(tmp_path: Path) -> None:
    text = r"""
\begin{table}
\caption{Synthetic results}
\label{tab:synthetic}
\begin{tabular}{lc}
Model & Accuracy \\
Proposed & 87.2\% \\
\end{tabular}
\end{table}
"""
    claim = _only_claim(tmp_path, text)

    assert claim.context.table_anchor == "label:tab:synthetic"
    assert claim.context.table_row == 1
    assert claim.context.table_column == 1
    assert "row=1" in claim.context.structural_anchor
    assert "column=1" in claim.context.structural_anchor


def test_application_prepares_classification_identity_and_migration_once(tmp_path: Path) -> None:
    scan, _, identities = _identify_files(
        tmp_path,
        {"main.tex": "Accuracy reaches 87.2\\%."},
    )
    previous = (ClaimIdentitySnapshot.from_claim(identities.claims[0]),)
    configuration = ProjectConfiguration(
        schema_version="1",
        sources=(),
        paper_paths=("main.tex",),
    )

    prepared = prepare_claim_identities(scan, configuration, previous=previous)

    assert prepared.identities.claims == identities.claims
    assert prepared.classifications.statistics.total_count == 1
    assert prepared.migrations[0].status is ClaimMigrationStatus.EXACT


def _identity_result(claim: IdentifiedClaim) -> ClaimIdentityResult:
    return ClaimIdentityResult(claims=(claim,))
