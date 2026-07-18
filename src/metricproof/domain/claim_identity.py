"""Stable, versioned identities and deterministic migration for paper Claims."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from pathlib import PurePosixPath, PureWindowsPath

from metricproof.domain.claims import (
    ClaimCandidateClassification,
    ClaimClassificationResult,
    ClaimDisposition,
    ClaimKind,
)
from metricproof.domain.models import NumericValue, SourceLocation
from metricproof.domain.paper import LatexTable, PaperScanResult, RawNumericCandidate

FINGERPRINT_VERSION = "1"
CLAIM_ID_DIGEST_LENGTH = 20
MIGRATION_MINIMUM_SCORE = 70
MIGRATION_MINIMUM_MARGIN = 15

_NUMBER_PATTERN = re.compile(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?(?:[eE][-+]?\d+)?(?![\w])")
_WHITESPACE_PATTERN = re.compile(r"\s+")
_CLAIM_ID_PATTERN = re.compile(r"clm_[0-9a-f]{20}\Z")


class ClaimMigrationStatus(StrEnum):
    """Outcome of reconciling one persistent Claim with a new paper scan."""

    EXACT = "exact"
    MIGRATED = "migrated"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"
    COLLISION = "collision"


class ClaimMigrationMethod(StrEnum):
    """Explainable matching tier used by a migration result."""

    STABLE_ID = "stable_id"
    VERSIONED_CONTEXT = "versioned_context"
    STRUCTURAL_CONTEXT = "structural_context"
    LOCAL_CONTEXT = "local_context"
    NONE = "none"


@dataclass(frozen=True, slots=True, order=True)
class StableClaimId:
    """Short opaque identifier that never embeds paper text or absolute paths."""

    value: str

    def __post_init__(self) -> None:
        if _CLAIM_ID_PATTERN.fullmatch(self.value) is None:
            raise ValueError("stable Claim IDs must use clm_ followed by 20 lowercase hex digits")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class ClaimContext:
    """Bounded, normalized source facts used to explain identity decisions."""

    summary: str
    structural_anchor: str
    prefix_anchor: str
    suffix_anchor: str
    syntactic_context: str
    occurrence_ordinal: int
    table_anchor: str | None = None
    table_row: int | None = None
    table_column: int | None = None

    def __post_init__(self) -> None:
        if self.occurrence_ordinal < 0:
            raise ValueError("Claim occurrence ordinals must be non-negative")
        if (self.table_row is None) != (self.table_column is None):
            raise ValueError("table row and column must be present together")


@dataclass(frozen=True, slots=True)
class ClaimFingerprint:
    """Versioned digest plus its reviewable, bounded composition facts."""

    version: str
    digest: str
    path: str
    structural_anchor: str
    context_digest: str
    semantic_digest: str
    components: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        windows_path = PureWindowsPath(self.path)
        if (
            not self.path
            or path.is_absolute()
            or windows_path.is_absolute()
            or ".." in path.parts
            or "\\" in self.path
        ):
            raise ValueError("Claim fingerprint paths must be project-relative POSIX paths")
        if self.version != FINGERPRINT_VERSION:
            raise ValueError(f"unsupported Claim fingerprint version: {self.version!r}")
        if not re.fullmatch(r"[0-9a-f]{64}", self.digest):
            raise ValueError("Claim fingerprint digest must be a SHA-256 hex digest")
        if not re.fullmatch(r"[0-9a-f]{20}", self.context_digest):
            raise ValueError("context digest must contain 20 lowercase hex digits")
        if not re.fullmatch(r"[0-9a-f]{20}", self.semantic_digest):
            raise ValueError("semantic digest must contain 20 lowercase hex digits")
        if tuple(sorted(self.components)) != self.components:
            raise ValueError("Claim fingerprint components must use stable key ordering")


@dataclass(frozen=True, slots=True)
class IdentifiedClaim:
    """A classified raw candidate with a stable identity and current location."""

    claim_id: StableClaimId
    fingerprint: ClaimFingerprint
    location: SourceLocation
    raw_text: str
    value: NumericValue
    kind: ClaimKind
    disposition: ClaimDisposition
    context: ClaimContext
    classification: ClaimCandidateClassification
    candidate_index: int

    def __post_init__(self) -> None:
        if self.candidate_index < 0:
            raise ValueError("candidate index must be non-negative")
        if self.location != self.classification.candidate.location:
            raise ValueError("identified Claim location must match its raw candidate")
        if self.raw_text != self.classification.candidate.raw_text:
            raise ValueError("identified Claim text must match its raw candidate")
        if self.kind is not self.classification.kind:
            raise ValueError("identified Claim kind must match its classification")
        if self.disposition is not self.classification.disposition:
            raise ValueError("identified Claim disposition must match its classification")


@dataclass(frozen=True, slots=True)
class ClaimIdentityCollision:
    """Two or more current Claims produced one truncated stable identity."""

    claim_id: StableClaimId
    locations: tuple[SourceLocation, ...]
    reason: str

    def __post_init__(self) -> None:
        if len(self.locations) < 2:
            raise ValueError("identity collisions require at least two locations")
        if tuple(sorted(self.locations)) != self.locations:
            raise ValueError("collision locations must use stable ordering")


@dataclass(frozen=True, slots=True)
class ClaimIdentityResult:
    """Current identified Claims and any explicit digest collisions."""

    claims: tuple[IdentifiedClaim, ...]
    collisions: tuple[ClaimIdentityCollision, ...] = ()

    def __post_init__(self) -> None:
        if tuple(sorted(self.claims, key=identified_claim_sort_key)) != self.claims:
            raise ValueError("identified Claims must use stable source ordering")
        if tuple(sorted(self.collisions, key=lambda item: item.claim_id.value)) != self.collisions:
            raise ValueError("Claim identity collisions must use stable ID ordering")


@dataclass(frozen=True, slots=True)
class ClaimIdentitySnapshot:
    """Persistent identity facts required for later deterministic migration."""

    claim_id: StableClaimId
    fingerprint: ClaimFingerprint
    location: SourceLocation
    raw_text: str
    kind: ClaimKind
    disposition: ClaimDisposition
    context: ClaimContext

    @classmethod
    def from_claim(cls, claim: IdentifiedClaim) -> ClaimIdentitySnapshot:
        return cls(
            claim_id=claim.claim_id,
            fingerprint=claim.fingerprint,
            location=claim.location,
            raw_text=claim.raw_text,
            kind=claim.kind,
            disposition=claim.disposition,
            context=claim.context,
        )


@dataclass(frozen=True, slots=True)
class ClaimMigrationResult:
    """Explainable reconciliation of one prior identity against current Claims."""

    previous_claim_id: StableClaimId
    status: ClaimMigrationStatus
    method: ClaimMigrationMethod
    score: int
    evidence: tuple[str, ...]
    conflicts: tuple[str, ...]
    old_location: SourceLocation
    new_location: SourceLocation | None = None
    generated_claim_id: StableClaimId | None = None
    resolved_claim: IdentifiedClaim | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("migration scores must be between 0 and 100")
        if self.status in {ClaimMigrationStatus.EXACT, ClaimMigrationStatus.MIGRATED}:
            if self.new_location is None or self.resolved_claim is None:
                raise ValueError("successful migration requires a resolved current Claim")
            if self.resolved_claim.claim_id != self.previous_claim_id:
                raise ValueError("successful migration must retain the persistent Claim ID")
        elif self.resolved_claim is not None:
            raise ValueError("unsuccessful migration cannot resolve a current Claim")
        if tuple(sorted(set(self.conflicts))) != self.conflicts:
            raise ValueError("migration conflicts must be unique and sorted")


@dataclass(frozen=True, slots=True)
class _IdentitySeed:
    classification: ClaimCandidateClassification
    candidate_index: int
    context: ClaimContext
    base_components: tuple[tuple[str, str], ...]


@dataclass(frozen=True, slots=True)
class _ScoredMigration:
    previous: ClaimIdentitySnapshot
    current: IdentifiedClaim
    score: int
    method: ClaimMigrationMethod
    evidence: tuple[str, ...]
    semantic_match: bool


def identify_claims(
    scan: PaperScanResult,
    classifications: ClaimClassificationResult,
    *,
    include_ambiguous: bool = False,
) -> ClaimIdentityResult:
    """Build stable identities for linkable classifications without reading files."""

    classification_by_candidate = {
        id(item.candidate): item for item in classifications.classifications
    }
    if len(classification_by_candidate) != len(classifications.classifications):
        raise ValueError("classification result contains a repeated candidate object")

    candidate_indexes = {id(candidate): index for index, candidate in enumerate(scan.candidates)}
    seeds: list[_IdentitySeed] = []
    for candidate in scan.candidates:
        classification = classification_by_candidate.get(id(candidate))
        if classification is None:
            raise ValueError("every scanned candidate must have one classification")
        if not _enters_identity_system(classification.disposition, include_ambiguous):
            continue
        table, row, column = _table_position(scan.tables, candidate)
        context = _claim_context(candidate, table=table, row=row, column=column, ordinal=0)
        seeds.append(
            _IdentitySeed(
                classification=classification,
                candidate_index=candidate_indexes[id(candidate)],
                context=context,
                base_components=_identity_components(classification, context),
            )
        )

    occurrence_counts: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)
    claims: list[IdentifiedClaim] = []
    for seed in seeds:
        ordinal = occurrence_counts[seed.base_components]
        occurrence_counts[seed.base_components] += 1
        context = replace(seed.context, occurrence_ordinal=ordinal)
        components = _identity_components(seed.classification, context)
        fingerprint = _fingerprint(seed.classification, context, components)
        candidate = seed.classification.candidate
        claims.append(
            IdentifiedClaim(
                claim_id=StableClaimId(f"clm_{fingerprint.digest[:CLAIM_ID_DIGEST_LENGTH]}"),
                fingerprint=fingerprint,
                location=candidate.location,
                raw_text=candidate.raw_text,
                value=candidate.value,
                kind=seed.classification.kind,
                disposition=seed.classification.disposition,
                context=context,
                classification=seed.classification,
                candidate_index=seed.candidate_index,
            )
        )

    ordered = tuple(sorted(claims, key=identified_claim_sort_key))
    collisions = _identity_collisions(ordered)
    return ClaimIdentityResult(claims=ordered, collisions=collisions)


def migrate_claims(
    previous: tuple[ClaimIdentitySnapshot, ...],
    current: ClaimIdentityResult,
) -> tuple[ClaimMigrationResult, ...]:
    """Reconcile old identities with a current scan using deterministic one-to-one tiers."""

    ordered_previous = tuple(
        sorted(previous, key=lambda item: (item.claim_id.value, item.location.display))
    )
    if len({item.claim_id for item in ordered_previous}) != len(ordered_previous):
        raise ValueError("previous Claim identities must have unique stable IDs")

    collision_ids = {item.claim_id for item in current.collisions}
    by_id: dict[StableClaimId, list[IdentifiedClaim]] = defaultdict(list)
    for claim in current.claims:
        by_id[claim.claim_id].append(claim)

    completed: dict[StableClaimId, ClaimMigrationResult] = {}
    claimed_current: set[int] = set()
    unresolved: list[ClaimIdentitySnapshot] = []
    for old in ordered_previous:
        exact = by_id.get(old.claim_id, [])
        if old.claim_id in collision_ids or len(exact) > 1:
            completed[old.claim_id] = _failed_migration(
                old,
                status=ClaimMigrationStatus.COLLISION,
                score=100,
                conflicts=("multiple current Claims share the prior stable ID",),
            )
        elif len(exact) == 1:
            match = exact[0]
            claimed_current.add(id(match))
            completed[old.claim_id] = _successful_migration(
                old,
                match,
                status=ClaimMigrationStatus.EXACT,
                method=ClaimMigrationMethod.STABLE_ID,
                score=100,
                evidence=("the versioned stable Claim ID matches exactly",),
            )
        else:
            unresolved.append(old)

    proposals: dict[StableClaimId, _ScoredMigration] = {}
    for old in unresolved:
        ranked = tuple(
            sorted(
                (
                    _score_migration(old, candidate)
                    for candidate in current.claims
                    if id(candidate) not in claimed_current
                ),
                key=lambda item: (-item.score, identified_claim_sort_key(item.current)),
            )
        )
        viable = tuple(item for item in ranked if item.score >= MIGRATION_MINIMUM_SCORE)
        if not viable:
            completed[old.claim_id] = _failed_migration(
                old,
                status=ClaimMigrationStatus.MISSING,
                score=ranked[0].score if ranked else 0,
                conflicts=("no current Claim met the deterministic migration threshold",),
            )
            continue
        top = viable[0]
        has_unique_semantic_tiebreak = (
            len(viable) > 1 and top.semantic_match and not viable[1].semantic_match
        )
        if (
            len(viable) > 1
            and top.score - viable[1].score < MIGRATION_MINIMUM_MARGIN
            and not has_unique_semantic_tiebreak
        ):
            completed[old.claim_id] = _failed_migration(
                old,
                status=ClaimMigrationStatus.AMBIGUOUS,
                score=top.score,
                conflicts=tuple(
                    sorted(
                        {
                            f"candidate {item.current.claim_id.value} scored {item.score}"
                            for item in viable[:5]
                        }
                    )
                ),
            )
            continue
        proposals[old.claim_id] = top

    proposals_by_current: dict[int, list[_ScoredMigration]] = defaultdict(list)
    for proposal in proposals.values():
        proposals_by_current[id(proposal.current)].append(proposal)
    for old_id, proposal in sorted(proposals.items(), key=lambda item: item[0].value):
        competing = proposals_by_current[id(proposal.current)]
        if len(competing) > 1:
            completed[old_id] = _failed_migration(
                proposal.previous,
                status=ClaimMigrationStatus.COLLISION,
                score=proposal.score,
                conflicts=tuple(
                    sorted(
                        f"prior Claim {item.previous.claim_id.value} selects the same current Claim"
                        for item in competing
                    )
                ),
            )
            continue
        completed[old_id] = _successful_migration(
            proposal.previous,
            proposal.current,
            status=ClaimMigrationStatus.MIGRATED,
            method=proposal.method,
            score=proposal.score,
            evidence=proposal.evidence,
        )

    return tuple(completed[item.claim_id] for item in ordered_previous)


def identified_claim_sort_key(claim: IdentifiedClaim) -> tuple[str, int, int, str]:
    return (
        claim.location.path,
        claim.location.char_start if claim.location.char_start is not None else -1,
        claim.location.char_end if claim.location.char_end is not None else -1,
        claim.claim_id.value,
    )


def _enters_identity_system(disposition: ClaimDisposition, include_ambiguous: bool) -> bool:
    return disposition in {
        ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
        ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM,
    } or (include_ambiguous and disposition is ClaimDisposition.AMBIGUOUS)


def _claim_context(
    candidate: RawNumericCandidate,
    *,
    table: LatexTable | None,
    row: int | None,
    column: int | None,
    ordinal: int,
) -> ClaimContext:
    prefix = _normalized_anchor(candidate.prefix[-96:])
    suffix = _normalized_anchor(candidate.suffix[:96])
    table_anchor = _table_anchor(table) if table is not None else None
    if table is not None and row is not None and column is not None:
        structural_anchor = "|".join(
            (
                f"table={table_anchor or table.environment.value}",
                f"row={row}",
                f"column={column}",
            )
        )
    else:
        environment = candidate.environments[-1] if candidate.environments else "document"
        command = candidate.command or "none"
        structural_anchor = (
            f"context={candidate.context.value}|environment={environment}|command={command}"
        )
    summary = _bounded_text(
        " ".join(item for item in (prefix, "<claim>", suffix) if item),
        240,
    )
    return ClaimContext(
        summary=summary,
        structural_anchor=structural_anchor,
        prefix_anchor=prefix,
        suffix_anchor=suffix,
        syntactic_context=candidate.context.value,
        occurrence_ordinal=ordinal,
        table_anchor=table_anchor,
        table_row=row,
        table_column=column,
    )


def _identity_components(
    classification: ClaimCandidateClassification,
    context: ClaimContext,
) -> tuple[tuple[str, str], ...]:
    candidate = classification.candidate
    components = {
        "fingerprint_version": FINGERPRINT_VERSION,
        "kind": classification.kind.value,
        "occurrence_ordinal": str(context.occurrence_ordinal),
        "path": candidate.location.path,
        "prefix_anchor": context.prefix_anchor,
        "structural_anchor": context.structural_anchor,
        "suffix_anchor": context.suffix_anchor,
        "syntactic_context": context.syntactic_context,
    }
    return tuple(sorted(components.items()))


def _fingerprint(
    classification: ClaimCandidateClassification,
    context: ClaimContext,
    components: tuple[tuple[str, str], ...],
) -> ClaimFingerprint:
    candidate = classification.candidate
    digest = _stable_digest(components)
    context_digest = _stable_digest(
        (
            ("prefix_anchor", context.prefix_anchor),
            ("structural_anchor", context.structural_anchor),
            ("suffix_anchor", context.suffix_anchor),
        )
    )[:20]
    semantic_digest = _stable_digest(
        (
            ("kind", classification.kind.value),
            ("numeric_unit", candidate.value.unit.value),
            ("numeric_value", str(candidate.value.canonical)),
        )
    )[:20]
    return ClaimFingerprint(
        version=FINGERPRINT_VERSION,
        digest=digest,
        path=candidate.location.path,
        structural_anchor=context.structural_anchor,
        context_digest=context_digest,
        semantic_digest=semantic_digest,
        components=components,
    )


def _stable_digest(components: tuple[tuple[str, str], ...]) -> str:
    payload = "\0".join(f"{key}={value}" for key, value in components)
    return sha256(payload.encode("utf-8")).hexdigest()


def _table_position(
    tables: tuple[LatexTable, ...], candidate: RawNumericCandidate
) -> tuple[LatexTable | None, int | None, int | None]:
    for table in tables:
        for row in table.rows:
            for cell in row.cells:
                if any(reference.candidate is candidate for reference in cell.numeric_references):
                    return table, row.row_index, cell.logical_column_start
    return None, None, None


def _table_anchor(table: LatexTable | None) -> str | None:
    if table is None:
        return None
    if table.label is not None and table.label.normalized_text:
        return f"label:{_normalized_anchor(table.label.normalized_text)}"
    if table.caption is not None and table.caption.normalized_text:
        return f"caption:{_normalized_anchor(table.caption.normalized_text)}"
    return None


def _normalized_anchor(value: str) -> str:
    without_numbers = _NUMBER_PATTERN.sub("<num>", value.casefold())
    return _bounded_text(_WHITESPACE_PATTERN.sub(" ", without_numbers).strip(), 120)


def _bounded_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    half = (limit - 3) // 2
    return f"{value[:half]}...{value[-half:]}"


def _identity_collisions(
    claims: tuple[IdentifiedClaim, ...],
) -> tuple[ClaimIdentityCollision, ...]:
    grouped: dict[StableClaimId, list[SourceLocation]] = defaultdict(list)
    for claim in claims:
        grouped[claim.claim_id].append(claim.location)
    return tuple(
        ClaimIdentityCollision(
            claim_id=claim_id,
            locations=tuple(sorted(locations)),
            reason="multiple current Claims share one truncated versioned fingerprint",
        )
        for claim_id, locations in sorted(grouped.items(), key=lambda item: item[0].value)
        if len(locations) > 1
    )


def _score_migration(
    previous: ClaimIdentitySnapshot,
    current: IdentifiedClaim,
) -> _ScoredMigration:
    score = 0
    evidence: list[str] = []
    if previous.kind is current.kind:
        score += 10
        evidence.append("Claim kind matches")
    if previous.fingerprint.version == current.fingerprint.version:
        score += 5
        evidence.append("fingerprint version matches")
    if previous.fingerprint.path == current.fingerprint.path:
        score += 20
        evidence.append("project-relative source path matches")
    if (
        previous.fingerprint.structural_anchor
        and previous.fingerprint.structural_anchor == current.fingerprint.structural_anchor
    ):
        score += 30
        evidence.append("structural anchor matches")
    if previous.fingerprint.context_digest == current.fingerprint.context_digest:
        score += 35
        evidence.append("bounded non-numeric context digest matches")
    else:
        prefix_similarity = _token_similarity(
            previous.context.prefix_anchor, current.context.prefix_anchor
        )
        suffix_similarity = _token_similarity(
            previous.context.suffix_anchor, current.context.suffix_anchor
        )
        context_points = round(20 * ((prefix_similarity + suffix_similarity) / 2))
        score += context_points
        if context_points:
            evidence.append(f"bounded local text similarity contributes {context_points} points")
    if (
        previous.context.table_anchor
        and previous.context.table_anchor == current.context.table_anchor
    ):
        score += 10
        evidence.append("table label or caption anchor matches")
    if previous.fingerprint.path == current.fingerprint.path:
        distance_points = _position_points(previous.location, current.location)
        score += distance_points
        if distance_points:
            evidence.append(f"nearby character position contributes {distance_points} points")

    semantic_match = previous.fingerprint.semantic_digest == current.fingerprint.semantic_digest
    if semantic_match:
        evidence.append("numeric semantic digest uniquely supports this migration")

    final_score = min(100, score)
    if previous.fingerprint.context_digest == current.fingerprint.context_digest:
        method = ClaimMigrationMethod.VERSIONED_CONTEXT
    elif previous.context.structural_anchor == current.context.structural_anchor:
        method = ClaimMigrationMethod.STRUCTURAL_CONTEXT
    else:
        method = ClaimMigrationMethod.LOCAL_CONTEXT
    return _ScoredMigration(
        previous=previous,
        current=current,
        score=final_score,
        method=method,
        evidence=tuple(evidence),
        semantic_match=semantic_match,
    )


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens and not right_tokens:
        return 1.0
    union = left_tokens | right_tokens
    if not union:
        return 0.0
    return len(left_tokens & right_tokens) / len(union)


def _position_points(left: SourceLocation, right: SourceLocation) -> int:
    if left.char_start is None or right.char_start is None:
        return 0
    distance = abs(left.char_start - right.char_start)
    if distance <= 64:
        return 10
    if distance <= 512:
        return 6
    if distance <= 4096:
        return 2
    return 0


def _successful_migration(
    previous: ClaimIdentitySnapshot,
    current: IdentifiedClaim,
    *,
    status: ClaimMigrationStatus,
    method: ClaimMigrationMethod,
    score: int,
    evidence: tuple[str, ...],
) -> ClaimMigrationResult:
    resolved = replace(current, claim_id=previous.claim_id)
    return ClaimMigrationResult(
        previous_claim_id=previous.claim_id,
        status=status,
        method=method,
        score=score,
        evidence=evidence,
        conflicts=(),
        old_location=previous.location,
        new_location=current.location,
        generated_claim_id=current.claim_id,
        resolved_claim=resolved,
    )


def _failed_migration(
    previous: ClaimIdentitySnapshot,
    *,
    status: ClaimMigrationStatus,
    score: int,
    conflicts: tuple[str, ...],
) -> ClaimMigrationResult:
    return ClaimMigrationResult(
        previous_claim_id=previous.claim_id,
        status=status,
        method=ClaimMigrationMethod.NONE,
        score=score,
        evidence=(),
        conflicts=tuple(sorted(set(conflicts))),
        old_location=previous.location,
    )
