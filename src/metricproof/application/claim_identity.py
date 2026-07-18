"""Application orchestration for Claim classification, identity, and migration."""

from __future__ import annotations

from dataclasses import dataclass

from metricproof.application.claims import classify_claim_candidates
from metricproof.application.configuration import ProjectConfiguration
from metricproof.domain.claim_identity import (
    ClaimIdentityResult,
    ClaimIdentitySnapshot,
    ClaimMigrationResult,
    identify_claims,
    migrate_claims,
)
from metricproof.domain.claims import ClaimClassificationResult
from metricproof.domain.paper import PaperScanResult


@dataclass(frozen=True, slots=True)
class PreparedClaimIdentities:
    """One scan's classification, current identities, and optional reconciliation."""

    classifications: ClaimClassificationResult
    identities: ClaimIdentityResult
    migrations: tuple[ClaimMigrationResult, ...]


def prepare_claim_identities(
    scan: PaperScanResult,
    configuration: ProjectConfiguration,
    *,
    previous: tuple[ClaimIdentitySnapshot, ...] = (),
    include_ambiguous: bool = False,
) -> PreparedClaimIdentities:
    """Reuse one prepared scan and deterministically reconcile prior identities."""

    classifications = classify_claim_candidates(scan, configuration)
    identities = identify_claims(
        scan,
        classifications,
        include_ambiguous=include_ambiguous,
    )
    migrations = migrate_claims(previous, identities) if previous else ()
    return PreparedClaimIdentities(
        classifications=classifications,
        identities=identities,
        migrations=migrations,
    )
