"""Application workflow models for reviewable, user-confirmed Claim linking."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

from metricproof.application.claim_identity import prepare_claim_identities
from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.matching import suggest_links_for_claim
from metricproof.domain.claim_identity import (
    ClaimIdentitySnapshot,
    ClaimMigrationResult,
    ClaimMigrationStatus,
    IdentifiedClaim,
)
from metricproof.domain.links import (
    DerivedLink,
    DirectLink,
    LinkScale,
    MetricReference,
    RoundingPolicy,
)
from metricproof.domain.matching import CandidateMatch, ClaimMatchResult, LinkSuggestionType
from metricproof.domain.models import ExperimentCatalog, MetricObservation
from metricproof.domain.paper import PaperScanResult
from metricproof.domain.registry import (
    ClaimRegistry,
    ClaimRegistryEntry,
    ClaimRegistryStatus,
    IgnoreReason,
    IgnoreRecord,
    RegistryMigrationRecord,
)


class LinkReviewStatus(StrEnum):
    UNLINKED = "unlinked"
    ACTIVE = "active"
    IGNORED = "ignored"
    BROKEN = "broken"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class LinkReviewItem:
    """One current or retained Claim decision shown by the link workflow."""

    claim_id: str
    status: LinkReviewStatus
    claim: IdentifiedClaim | None
    existing_entry: ClaimRegistryEntry | None
    migration: ClaimMigrationResult | None
    matches: ClaimMatchResult | None

    def __post_init__(self) -> None:
        if self.claim is not None and self.claim.claim_id.value != self.claim_id:
            raise ValueError("review Claim ID must match the current Claim")
        if self.existing_entry is not None and self.existing_entry.claim_id != self.claim_id:
            raise ValueError("review Claim ID must match the registry entry")
        if self.matches is not None and self.matches.claim.claim_id.value != self.claim_id:
            raise ValueError("review Claim ID must match its suggestions")

    @property
    def reviewable(self) -> bool:
        return self.claim is not None and self.status in {
            LinkReviewStatus.UNLINKED,
            LinkReviewStatus.BROKEN,
            LinkReviewStatus.ACTIVE,
        }


@dataclass(frozen=True, slots=True)
class LinkSession:
    """One scan, catalog, registry, migration, and suggestion snapshot."""

    registry: ClaimRegistry
    items: tuple[LinkReviewItem, ...]
    identity_collisions: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if tuple(sorted(self.items, key=link_review_sort_key)) != self.items:
            raise ValueError("link review items must use stable source ordering")
        if tuple(sorted(set(self.identity_collisions))) != self.identity_collisions:
            raise ValueError("identity collision summaries must be unique and sorted")

    def get(self, claim_id: str) -> LinkReviewItem | None:
        return next((item for item in self.items if item.claim_id == claim_id), None)


def build_link_session(
    scan: PaperScanResult,
    configuration: ProjectConfiguration,
    catalog: ExperimentCatalog,
    registry: ClaimRegistry,
) -> LinkSession:
    """Reconcile one prepared scan and rank suggestions without any writes."""

    previous = tuple(entry.identity for entry in registry.entries)
    prepared = prepare_claim_identities(scan, configuration, previous=previous)
    migration_by_id = {item.previous_claim_id.value: item for item in prepared.migrations}
    claimed_generated_ids: set[str] = set()
    items: list[LinkReviewItem] = []

    for entry in registry.entries:
        migration = migration_by_id.get(entry.claim_id)
        claim: IdentifiedClaim | None = None
        if migration is not None and migration.resolved_claim is not None:
            claim = migration.resolved_claim
            if migration.generated_claim_id is not None:
                claimed_generated_ids.add(migration.generated_claim_id.value)
        status = _retained_status(entry, migration, catalog)
        matches = (
            suggest_links_for_claim(claim, catalog, configuration)
            if claim is not None and status in {LinkReviewStatus.ACTIVE, LinkReviewStatus.BROKEN}
            else None
        )
        items.append(
            LinkReviewItem(
                claim_id=entry.claim_id,
                status=status,
                claim=claim,
                existing_entry=entry,
                migration=migration,
                matches=matches,
            )
        )

    for claim in prepared.identities.claims:
        if claim.claim_id.value in claimed_generated_ids:
            continue
        matches = suggest_links_for_claim(claim, catalog, configuration)
        items.append(
            LinkReviewItem(
                claim_id=claim.claim_id.value,
                status=LinkReviewStatus.UNLINKED,
                claim=claim,
                existing_entry=None,
                migration=None,
                matches=matches,
            )
        )

    collisions = tuple(
        sorted(
            f"{collision.claim_id.value}: {collision.reason}"
            for collision in prepared.identities.collisions
        )
    )
    return LinkSession(
        registry=registry,
        items=tuple(sorted(items, key=link_review_sort_key)),
        identity_collisions=collisions,
    )


def entry_from_candidate(
    item: LinkReviewItem,
    candidate: CandidateMatch,
    *,
    scale: LinkScale | None = None,
    note: str = "",
) -> ClaimRegistryEntry:
    """Materialize one explicitly selected suggestion as a persistent decision."""

    claim = _review_claim(item)
    if item.matches is None or candidate not in item.matches.candidates:
        raise ValueError("the selected candidate does not belong to this Claim review")
    selected_scale = scale or candidate.suggested_scale
    fingerprint = claim.fingerprint.digest
    if candidate.suggestion_type is LinkSuggestionType.DIRECT:
        if candidate.metric is None:
            raise ValueError("direct suggestions require a metric")
        link = DirectLink(
            claim_id=claim.claim_id,
            metric=replace(candidate.metric, scale=selected_scale),
            confirmed_fingerprint=fingerprint,
            note=note,
        )
    else:
        if candidate.operation is None or candidate.output_unit is None:
            raise ValueError("derived suggestions require operation and output semantics")
        link = DerivedLink(
            claim_id=claim.claim_id,
            operation=candidate.operation,
            operands=candidate.operands,
            output_unit=candidate.output_unit,
            output_scale=selected_scale,
            confirmed_fingerprint=fingerprint,
            rounding=RoundingPolicy(decimal_places=claim.value.decimal_places),
            standard_deviation_mode=candidate.standard_deviation_mode,
            note=note,
        )
    return ClaimRegistryEntry(
        identity=ClaimIdentitySnapshot.from_claim(claim),
        status=ClaimRegistryStatus.ACTIVE,
        link=link,
        note=note,
        migration=_migration_record(item.migration),
    )


def entry_from_observation(
    item: LinkReviewItem,
    observation: MetricObservation,
    *,
    scale: LinkScale,
    note: str = "",
) -> ClaimRegistryEntry:
    """Create an explicit manual DirectLink from a user-selected observation."""

    claim = _review_claim(item)
    metric = MetricReference(
        source_file=observation.source_file,
        run_id=observation.run_id,
        metric_name=observation.metric_name,
        source_selector=observation.source_selector,
        scale=scale,
    )
    return ClaimRegistryEntry(
        identity=ClaimIdentitySnapshot.from_claim(claim),
        status=ClaimRegistryStatus.ACTIVE,
        link=DirectLink(
            claim_id=claim.claim_id,
            metric=metric,
            confirmed_fingerprint=claim.fingerprint.digest,
            note=note,
        ),
        note=note,
        migration=_migration_record(item.migration),
    )


def ignored_entry(
    item: LinkReviewItem,
    *,
    reason: IgnoreReason = IgnoreReason.USER_DECISION,
    note: str = "",
) -> ClaimRegistryEntry:
    """Persist a user's explicit ignore decision for a current Claim."""

    claim = _review_claim(item)
    return ClaimRegistryEntry(
        identity=ClaimIdentitySnapshot.from_claim(claim),
        status=ClaimRegistryStatus.IGNORED,
        ignore=IgnoreRecord(reason=reason, note=note),
        note=note,
        migration=_migration_record(item.migration),
    )


def link_review_sort_key(item: LinkReviewItem) -> tuple[str, int, str]:
    if item.claim is not None:
        location = item.claim.location
    elif item.existing_entry is not None:
        location = item.existing_entry.identity.location
    else:
        return ("", -1, item.claim_id)
    return (
        location.path,
        location.char_start if location.char_start is not None else -1,
        item.claim_id,
    )


def _retained_status(
    entry: ClaimRegistryEntry,
    migration: ClaimMigrationResult | None,
    catalog: ExperimentCatalog,
) -> LinkReviewStatus:
    if entry.status is ClaimRegistryStatus.IGNORED:
        return LinkReviewStatus.IGNORED
    if migration is None or migration.status is ClaimMigrationStatus.MISSING:
        return LinkReviewStatus.MISSING
    if migration.status in {ClaimMigrationStatus.AMBIGUOUS, ClaimMigrationStatus.COLLISION}:
        return LinkReviewStatus.AMBIGUOUS
    if entry.link is None or not _link_available(entry, catalog):
        return LinkReviewStatus.BROKEN
    return LinkReviewStatus.ACTIVE


def _link_available(entry: ClaimRegistryEntry, catalog: ExperimentCatalog) -> bool:
    if entry.link is None:
        return False
    references = (
        (entry.link.metric,)
        if isinstance(entry.link, DirectLink)
        else tuple(operand.metric for operand in entry.link.operands)
    )
    available = {
        (
            item.source_file,
            item.run_id,
            item.metric_name,
            item.source_selector,
        )
        for item in catalog.observations
    }
    return all(
        (reference.source_file, reference.run_id, reference.metric_name, reference.source_selector)
        in available
        for reference in references
    )


def _review_claim(item: LinkReviewItem) -> IdentifiedClaim:
    if item.claim is None:
        raise ValueError("a missing or ambiguous historical Claim cannot be linked")
    return item.claim


def _migration_record(
    migration: ClaimMigrationResult | None,
) -> RegistryMigrationRecord | None:
    if migration is None:
        return None
    return RegistryMigrationRecord(
        status=migration.status,
        method=migration.method,
        score=migration.score,
        previous_path=migration.old_location.path,
        current_path=migration.new_location.path if migration.new_location is not None else None,
        evidence=migration.evidence,
        conflicts=migration.conflicts,
    )
