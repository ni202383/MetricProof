"""Application service for non-persistent Claim candidate classification."""

from __future__ import annotations

from metricproof.application.configuration import ProjectConfiguration
from metricproof.domain.claims import ClaimClassificationResult, classify_raw_candidates
from metricproof.domain.paper import PaperScanResult


def classify_claim_candidates(
    scan: PaperScanResult,
    configuration: ProjectConfiguration,
) -> ClaimClassificationResult:
    """Classify one prepared scan using validated metric aliases."""

    metric_terms = tuple(
        term
        for canonical, aliases in configuration.metric_aliases
        for term in (canonical, *aliases)
    )
    return classify_raw_candidates(scan, additional_metric_terms=metric_terms)
