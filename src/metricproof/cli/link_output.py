"""Pure payload and terminal rendering helpers for the link workflow."""

from __future__ import annotations

import sys
from collections import Counter

import typer
from rich.console import Console
from rich.table import Table

from metricproof.application.linking import LinkReviewItem, LinkSession
from metricproof.domain.matching import CandidateMatch, LinkSuggestionType


def link_session_payload(session: LinkSession, *, selected_claim: str | None) -> dict[str, object]:
    """Return stable JSON-ready data without Rich objects or absolute paths."""

    items = tuple(
        item for item in session.items if selected_claim is None or item.claim_id == selected_claim
    )
    counts = Counter(item.status.value for item in items)
    return {
        "schema_version": "1",
        "command": "link",
        "ok": True,
        "write_performed": False,
        "summary": {
            "claim_count": len(items),
            "unlinked_count": counts["unlinked"],
            "active_count": counts["active"],
            "ignored_count": counts["ignored"],
            "broken_count": counts["broken"],
            "ambiguous_count": counts["ambiguous"],
            "missing_count": counts["missing"],
            "identity_collision_count": len(session.identity_collisions),
        },
        "identity_collisions": list(session.identity_collisions),
        "claims": [_review_payload(item) for item in items],
    }


def render_link_session(
    session: LinkSession,
    *,
    selected_claim: str | None,
    show_broken: bool,
) -> tuple[LinkReviewItem, ...]:
    """Render a stable overview and return the items eligible for interactive review."""

    displayed = tuple(
        item
        for item in session.items
        if (selected_claim is None or item.claim_id == selected_claim)
        and (
            selected_claim is not None
            or item.status.value == "unlinked"
            or (show_broken and item.status.value == "broken")
        )
    )
    typer.echo(
        f"Claim link review: {len(session.items)} Claim(s), "
        f"{sum(item.status.value == 'unlinked' for item in session.items)} unlinked, "
        f"{sum(item.status.value == 'active' for item in session.items)} active, "
        f"{sum(item.status.value == 'ignored' for item in session.items)} ignored, "
        f"{sum(item.status.value == 'broken' for item in session.items)} broken, "
        f"{sum(item.status.value == 'ambiguous' for item in session.items)} ambiguous, "
        f"{sum(item.status.value == 'missing' for item in session.items)} missing."
    )
    if not displayed:
        typer.echo("No Claims match the current link review filter.")
        return ()
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=180)
    table = Table(title="MetricProof Claim link review", show_lines=True)
    table.add_column("Claim ID")
    table.add_column("Status")
    table.add_column("Location")
    table.add_column("Displayed")
    table.add_column("Kind")
    table.add_column("Top suggestion")
    for item in displayed:
        claim = item.claim
        top = item.matches.candidates[0] if item.matches and item.matches.candidates else None
        table.add_row(
            item.claim_id,
            item.status.value,
            _location(item),
            claim.raw_text if claim is not None else "",
            claim.kind.value if claim is not None else "",
            _candidate_summary(top),
        )
    console.print(table)
    return displayed


def render_match_candidates(item: LinkReviewItem) -> None:
    """Show candidate totals and every contributing feature before prompting."""

    if item.matches is None or not item.matches.candidates:
        typer.echo(
            "No deterministic candidate met the threshold; manual metric selection is available."
        )
        return
    console = Console(file=sys.stdout, color_system=None, force_terminal=False, width=190)
    table = Table(title=f"Suggestions for {item.claim_id}", show_lines=True)
    table.add_column("#", justify="right")
    table.add_column("Type")
    table.add_column("Score", justify="right")
    table.add_column("Target")
    table.add_column("Scale")
    table.add_column("Evidence")
    table.add_column("Uncertainty")
    for index, candidate in enumerate(item.matches.candidates, start=1):
        table.add_row(
            str(index),
            candidate.suggestion_type.value,
            str(candidate.score),
            _candidate_target(candidate),
            candidate.suggested_scale.value,
            "; ".join(
                f"{feature.code} {feature.contribution:+d}: {feature.summary}"
                for feature in candidate.features
            ),
            "; ".join(candidate.uncertainties),
        )
    console.print(table)
    if item.matches.ambiguous:
        typer.echo("Leading suggestions are close; MetricProof will not select one automatically.")


def candidate_payload(candidate: CandidateMatch) -> dict[str, object]:
    payload: dict[str, object] = {
        "type": candidate.suggestion_type.value,
        "score": candidate.score,
        "suggested_scale": candidate.suggested_scale.value,
        "features": [
            {
                "code": feature.code,
                "contribution": feature.contribution,
                "summary": feature.summary,
            }
            for feature in candidate.features
        ],
        "uncertainties": list(candidate.uncertainties),
    }
    if candidate.metric is not None:
        payload["metric"] = _metric_payload(candidate.metric)
    else:
        payload.update(
            {
                "operation": candidate.operation.value if candidate.operation else None,
                "operands": [
                    {"name": operand.name, "metric": _metric_payload(operand.metric)}
                    for operand in candidate.operands
                ],
                "output_unit": candidate.output_unit.value if candidate.output_unit else None,
                "standard_deviation_mode": (
                    candidate.standard_deviation_mode.value
                    if candidate.standard_deviation_mode
                    else None
                ),
            }
        )
    return payload


def _review_payload(item: LinkReviewItem) -> dict[str, object]:
    claim = item.claim
    migration = item.migration
    return {
        "claim_id": item.claim_id,
        "status": item.status.value,
        "location": _location(item),
        "raw_text": claim.raw_text if claim is not None else None,
        "kind": claim.kind.value if claim is not None else None,
        "disposition": claim.disposition.value if claim is not None else None,
        "context_summary": claim.context.summary if claim is not None else None,
        "migration": (
            {
                "status": migration.status.value,
                "method": migration.method.value,
                "score": migration.score,
                "old_location": migration.old_location.display,
                "new_location": migration.new_location.display if migration.new_location else None,
                "evidence": list(migration.evidence),
                "conflicts": list(migration.conflicts),
            }
            if migration is not None
            else None
        ),
        "match_ambiguous": item.matches.ambiguous if item.matches is not None else False,
        "match_uncertainties": (
            list(item.matches.uncertainties) if item.matches is not None else []
        ),
        "candidates": (
            [candidate_payload(candidate) for candidate in item.matches.candidates]
            if item.matches is not None
            else []
        ),
    }


def _metric_payload(metric: object) -> dict[str, object]:
    from metricproof.domain.links import MetricReference

    if not isinstance(metric, MetricReference):
        raise TypeError("candidate metric payload requires MetricReference")
    return {
        "source_file": metric.source_file,
        "run_id": metric.run_id,
        "metric_name": metric.metric_name,
        "source_selector": metric.source_selector,
        "scale": metric.scale.value,
    }


def _candidate_summary(candidate: CandidateMatch | None) -> str:
    if candidate is None:
        return "none"
    return f"{candidate.score}: {_candidate_target(candidate)}"


def _candidate_target(candidate: CandidateMatch) -> str:
    if candidate.suggestion_type is LinkSuggestionType.DIRECT and candidate.metric is not None:
        return f"{candidate.metric.run_id}/{candidate.metric.metric_name}"
    return (
        f"{candidate.operation.value if candidate.operation else 'derived'}("
        + ", ".join(
            f"{item.name}={item.metric.run_id}/{item.metric.metric_name}"
            for item in candidate.operands
        )
        + ")"
    )


def _location(item: LinkReviewItem) -> str:
    if item.claim is not None:
        return item.claim.location.display
    if item.existing_entry is not None:
        return item.existing_entry.identity.location.display
    return ""
