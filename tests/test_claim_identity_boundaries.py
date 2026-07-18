from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

import metricproof.domain.claim_identity as identity_module
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.domain.claim_identity import (
    FINGERPRINT_VERSION,
    ClaimIdentityCollision,
    ClaimIdentityResult,
    ClaimIdentitySnapshot,
    ClaimMigrationMethod,
    ClaimMigrationResult,
    ClaimMigrationStatus,
    StableClaimId,
    identify_claims,
    migrate_claims,
)
from metricproof.domain.claims import (
    ClaimClassificationResult,
    ClaimClassificationStatistics,
    ClaimDisposition,
    ClaimKind,
    classify_raw_candidates,
)


def _scan(root: Path, files: dict[str, str]):
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    scan = LocalLatexPaperScanner().scan(root, tuple(sorted(files)))
    classifications = classify_raw_candidates(scan)
    identities = identify_claims(scan, classifications, include_ambiguous=True)
    return scan, classifications, identities


def _claim(root: Path):
    _, _, identities = _scan(root, {"main.tex": "Accuracy reaches 87.2\\%."})
    assert len(identities.claims) == 1
    return identities.claims[0]


@pytest.mark.parametrize(
    "value",
    ["", "clm_123", "CLM_00000000000000000000", "clm_gggggggggggggggggggg", "x" * 24],
)
def test_stable_claim_id_rejects_noncanonical_values(value: str) -> None:
    with pytest.raises(ValueError, match="stable Claim IDs"):
        StableClaimId(value)


def test_context_and_fingerprint_invariants(tmp_path: Path) -> None:
    claim = _claim(tmp_path)
    context = claim.context
    fingerprint = claim.fingerprint

    with pytest.raises(ValueError, match="ordinals"):
        replace(context, occurrence_ordinal=-1)
    with pytest.raises(ValueError, match="row and column"):
        replace(context, table_row=0, table_column=None)

    invalid_fingerprints: tuple[tuple[dict[str, object], str], ...] = (
        ({"path": ""}, "project-relative"),
        ({"path": "C:/paper.tex"}, "project-relative"),
        ({"path": "../paper.tex"}, "project-relative"),
        ({"version": "2"}, "unsupported"),
        ({"digest": "0" * 63}, "SHA-256"),
        ({"context_digest": "0" * 19}, "context digest"),
        ({"semantic_digest": "Z" * 20}, "semantic digest"),
        ({"components": tuple(reversed(fingerprint.components))}, "stable key ordering"),
    )
    for changes, message in invalid_fingerprints:
        with pytest.raises(ValueError, match=message):
            replace(fingerprint, **changes)

    assert fingerprint.version == FINGERPRINT_VERSION
    assert str(claim.claim_id) == claim.claim_id.value


def test_identified_claim_and_collision_invariants(tmp_path: Path) -> None:
    claim = _claim(tmp_path)
    other_location = replace(claim.location, column=(claim.location.column or 1) + 1)

    invalid_claims: tuple[tuple[dict[str, object], str], ...] = (
        ({"candidate_index": -1}, "candidate index"),
        ({"location": other_location}, "location"),
        ({"raw_text": "different"}, "text"),
        ({"kind": ClaimKind.UNKNOWN}, "kind"),
        ({"disposition": ClaimDisposition.AMBIGUOUS}, "disposition"),
    )
    for changes, message in invalid_claims:
        with pytest.raises(ValueError, match=message):
            replace(claim, **changes)

    with pytest.raises(ValueError, match="at least two"):
        ClaimIdentityCollision(claim.claim_id, (claim.location,), "collision")
    later = replace(
        claim.location,
        char_start=(claim.location.char_start or 0) + 10,
        char_end=(claim.location.char_end or 0) + 10,
    )
    with pytest.raises(ValueError, match="stable ordering"):
        ClaimIdentityCollision(claim.claim_id, (later, claim.location), "collision")


def test_identity_result_requires_stable_claim_and_collision_order(tmp_path: Path) -> None:
    _, _, identities = _scan(
        tmp_path,
        {
            "a.tex": "Accuracy reaches 87.2\\%.",
            "b.tex": "F1 reaches 0.913.",
        },
    )
    assert len(identities.claims) == 2
    with pytest.raises(ValueError, match="stable source ordering"):
        ClaimIdentityResult(claims=tuple(reversed(identities.claims)))

    locations = tuple(sorted(claim.location for claim in identities.claims))
    first = ClaimIdentityCollision(StableClaimId("clm_00000000000000000000"), locations, "x")
    second = ClaimIdentityCollision(StableClaimId("clm_11111111111111111111"), locations, "y")
    with pytest.raises(ValueError, match="stable ID ordering"):
        ClaimIdentityResult(claims=(), collisions=(second, first))


def test_identification_requires_complete_classification(tmp_path: Path) -> None:
    scan, classifications, _ = _scan(
        tmp_path,
        {"main.tex": "Accuracy reaches 87.2\\%. F1 reaches 0.913."},
    )
    first = classifications.classifications[0]
    incomplete = ClaimClassificationResult(
        classifications=(first,),
        statistics=ClaimClassificationStatistics(
            total_count=1,
            likely_count=int(first.disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM),
            possible_count=int(first.disposition is ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM),
            ambiguous_count=int(first.disposition is ClaimDisposition.AMBIGUOUS),
            non_experiment_count=int(first.disposition is ClaimDisposition.NON_EXPERIMENT),
        ),
    )

    with pytest.raises(ValueError, match="every scanned candidate"):
        identify_claims(scan, incomplete)


def test_migration_rejects_duplicate_prior_ids_and_current_exact_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim = _claim(tmp_path)
    snapshot = ClaimIdentitySnapshot.from_claim(claim)
    with pytest.raises(ValueError, match="unique stable IDs"):
        migrate_claims((snapshot, snapshot), ClaimIdentityResult(claims=(claim,)))

    def colliding_digest(components: tuple[tuple[str, str], ...]) -> str:
        assert components
        return "1" * 64

    monkeypatch.setattr(identity_module, "_stable_digest", colliding_digest)
    _, _, current = _scan(
        tmp_path,
        {"main.tex": "Accuracy reaches 87.2\\%. F1 reaches 0.913."},
    )
    collision_snapshot = ClaimIdentitySnapshot.from_claim(current.claims[0])
    result = migrate_claims((collision_snapshot,), current)[0]
    assert result.status is ClaimMigrationStatus.COLLISION
    assert result.score == 100
    assert result.conflicts == ("multiple current Claims share the prior stable ID",)


def test_migration_result_invariants(tmp_path: Path) -> None:
    claim = _claim(tmp_path)
    snapshot = ClaimIdentitySnapshot.from_claim(claim)
    valid = migrate_claims((snapshot,), ClaimIdentityResult(claims=(claim,)))[0]
    assert valid.status is ClaimMigrationStatus.EXACT

    with pytest.raises(ValueError, match="between 0 and 100"):
        replace(valid, score=101)
    with pytest.raises(ValueError, match="resolved current Claim"):
        replace(valid, new_location=None)
    with pytest.raises(ValueError, match="persistent Claim ID"):
        replace(valid, resolved_claim=replace(claim, claim_id=StableClaimId("clm_" + "f" * 20)))

    failed = ClaimMigrationResult(
        previous_claim_id=snapshot.claim_id,
        status=ClaimMigrationStatus.MISSING,
        method=ClaimMigrationMethod.NONE,
        score=0,
        evidence=(),
        conflicts=("missing",),
        old_location=snapshot.location,
    )
    with pytest.raises(ValueError, match="cannot resolve"):
        replace(failed, resolved_claim=claim)
    with pytest.raises(ValueError, match="unique and sorted"):
        replace(failed, conflicts=("z", "a", "a"))


def test_caption_and_unanchored_tables_have_explicit_context(tmp_path: Path) -> None:
    _, _, captioned = _scan(
        tmp_path,
        {
            "caption.tex": r"""
\begin{table}
\caption{Synthetic 2026 scores}
\begin{tabular}{lc}
Model & Accuracy \\
Proposed & 87.2\% \\
\end{tabular}
\end{table}
"""
        },
    )
    table_claim = next(claim for claim in captioned.claims if claim.raw_text == r"87.2\%")
    assert table_claim.context.table_anchor == "caption:synthetic <num> scores"

    _, _, unanchored = _scan(
        tmp_path,
        {"plain.tex": r"\begin{tabular}{lc}Model & Accuracy \\ Proposed & 87.2\%\end{tabular}"},
    )
    assert unanchored.claims[0].context.table_anchor is None
    assert "table=tabular" in unanchored.claims[0].context.structural_anchor


def test_long_context_is_bounded(tmp_path: Path) -> None:
    long_caption = "synthetic context " * 30
    _, _, identities = _scan(
        tmp_path,
        {
            "long.tex": rf"""
\begin{{table}}
\caption{{{long_caption}}}
\begin{{tabular}}{{lc}}
Model & Accuracy \\
Proposed & 87.2\% \\
\end{{tabular}}
\end{{table}}
"""
        },
    )
    claim = next(claim for claim in identities.claims if claim.raw_text == r"87.2\%")
    assert claim.context.table_anchor is not None
    assert "..." in claim.context.table_anchor
    assert len(claim.context.summary) <= 240
