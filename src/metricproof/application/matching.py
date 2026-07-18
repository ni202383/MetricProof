"""Application boundary for explainable Claim-to-metric suggestions."""

from metricproof.application.configuration import ProjectConfiguration
from metricproof.domain.claim_identity import IdentifiedClaim
from metricproof.domain.matching import (
    ClaimMatchResult,
    suggest_all_claim_matches,
    suggest_claim_matches,
)
from metricproof.domain.models import ExperimentCatalog


def suggest_links_for_claim(
    claim: IdentifiedClaim,
    catalog: ExperimentCatalog,
    configuration: ProjectConfiguration,
) -> ClaimMatchResult:
    """Adapt validated configuration aliases to the pure domain matcher."""

    return suggest_claim_matches(claim, catalog, configuration.metric_aliases)


def suggest_links(
    claims: tuple[IdentifiedClaim, ...],
    catalog: ExperimentCatalog,
    configuration: ProjectConfiguration,
) -> tuple[ClaimMatchResult, ...]:
    """Match a prepared Claim set without reading files or persisting decisions."""

    return suggest_all_claim_matches(claims, catalog, configuration.metric_aliases)
