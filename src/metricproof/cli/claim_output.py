"""Console and JSON presentation for non-persistent Claim classifications."""

from __future__ import annotations

import sys

from rich.console import Console
from rich.table import Table

from metricproof.domain.claims import (
    ClaimCandidateClassification,
    ClaimClassificationResult,
    ClaimDisposition,
)
from metricproof.domain.models import SourceLocation
from metricproof.domain.paper import RawNumericCandidate


def displayed_claim_classifications(
    result: ClaimClassificationResult,
    *,
    show_all: bool,
) -> tuple[ClaimCandidateClassification, ...]:
    """Select the default review queue or the full debug set."""

    if show_all:
        return result.classifications
    visible = {
        ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
        ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM,
    }
    return tuple(item for item in result.classifications if item.disposition in visible)


def render_claim_classifications(
    result: ClaimClassificationResult,
    *,
    show_all: bool,
) -> None:
    """Render a review-oriented classification table."""

    displayed = displayed_claim_classifications(result, show_all=show_all)
    if not displayed:
        print("No Claim classifications matched the current display filter.")
        return
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=220)
    table = Table(title="MetricProof Claim candidate classifications", show_lines=True)
    table.add_column("File")
    table.add_column("Line", justify="right")
    table.add_column("Column", justify="right")
    table.add_column("Raw")
    table.add_column("Kind")
    table.add_column("Disposition")
    table.add_column("Score", justify="right")
    table.add_column("Confidence")
    table.add_column("Review")
    table.add_column("Key evidence")
    for item in displayed:
        candidate = item.candidate
        table.add_row(
            candidate.location.path,
            str(candidate.location.line or ""),
            str(candidate.location.column or ""),
            candidate.raw_text,
            item.kind.value,
            item.disposition.value,
            str(item.score),
            item.confidence.value,
            "yes" if item.review_recommended else "no",
            _key_evidence(item),
        )
    console.print(table)


def classification_payloads(
    result: ClaimClassificationResult,
    candidates: tuple[RawNumericCandidate, ...],
) -> list[dict[str, object]]:
    """Serialize classifications using scan-local candidate indexes."""

    candidate_indexes = {id(candidate): index for index, candidate in enumerate(candidates)}
    return [
        {
            "candidate_index": candidate_indexes[id(item.candidate)],
            "kind": item.kind.value,
            "disposition": item.disposition.value,
            "score": item.score,
            "confidence": item.confidence.value,
            "review_recommended": item.review_recommended,
            "evidence": [
                {
                    "reason_code": evidence.reason_code,
                    "direction": evidence.direction.value,
                    "score_impact": evidence.score_impact,
                    "explanation": evidence.explanation,
                    "location": _location_payload(evidence.location),
                    "structural_context": list(evidence.structural_context),
                }
                for evidence in item.evidence
            ],
        }
        for item in result.classifications
    ]


def _key_evidence(item: ClaimCandidateClassification) -> str:
    ordered = sorted(
        item.evidence,
        key=lambda evidence: (-abs(evidence.score_impact), evidence.reason_code),
    )
    return "; ".join(
        f"{evidence.reason_code} ({evidence.score_impact:+d})" for evidence in ordered[:3]
    )


def _location_payload(location: SourceLocation) -> dict[str, object]:
    return {
        "path": location.path,
        "selector": location.selector,
        "line": location.line,
        "column": location.column,
        "end_line": location.end_line,
        "end_column": location.end_column,
        "char_start": location.char_start,
        "char_end": location.char_end,
    }
