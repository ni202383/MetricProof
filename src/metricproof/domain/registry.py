"""Strict domain representation of the persistent Claim registry."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from metricproof.domain.claim_identity import (
    ClaimIdentitySnapshot,
    ClaimMigrationMethod,
    ClaimMigrationStatus,
)
from metricproof.domain.links import ClaimLink, DirectLink

CLAIM_REGISTRY_SCHEMA_VERSION = "1"


class ClaimRegistryStatus(StrEnum):
    ACTIVE = "active"
    IGNORED = "ignored"
    BROKEN = "broken"
    AMBIGUOUS = "ambiguous"
    MISSING = "missing"


class IgnoreReason(StrEnum):
    NON_EXPERIMENTAL_NUMBER = "non_experimental_number"
    OUT_OF_SCOPE = "out_of_scope"
    UNSUPPORTED_SYNTAX = "unsupported_syntax"
    USER_DECISION = "user_decision"


@dataclass(frozen=True, slots=True)
class IgnoreRecord:
    reason: IgnoreReason
    note: str = ""


@dataclass(frozen=True, slots=True)
class RegistryMigrationRecord:
    status: ClaimMigrationStatus
    method: ClaimMigrationMethod
    score: int
    previous_path: str
    current_path: str | None
    evidence: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 100:
            raise ValueError("registry migration scores must be between 0 and 100")
        if tuple(sorted(set(self.conflicts))) != self.conflicts:
            raise ValueError("registry migration conflicts must be unique and sorted")


@dataclass(frozen=True, slots=True)
class ClaimRegistryEntry:
    """One retained user decision plus the identity facts required to migrate it."""

    identity: ClaimIdentitySnapshot
    status: ClaimRegistryStatus
    link: ClaimLink | None = None
    ignore: IgnoreRecord | None = None
    note: str = ""
    migration: RegistryMigrationRecord | None = None

    def __post_init__(self) -> None:
        if (self.link is None) == (self.ignore is None):
            raise ValueError("registry entries require exactly one link or ignore decision")
        if self.link is not None and self.link.claim_id != self.identity.claim_id:
            raise ValueError("registry link Claim ID must match the entry identity")
        if self.status is ClaimRegistryStatus.ACTIVE:
            if self.link is None:
                raise ValueError("active registry entries require a link")
        elif self.status is ClaimRegistryStatus.IGNORED:
            if self.ignore is None:
                raise ValueError("ignored registry entries require an ignore decision")
        elif self.status is ClaimRegistryStatus.BROKEN and self.link is None:
            raise ValueError("broken registry entries must retain their link")

    @property
    def claim_id(self) -> str:
        return self.identity.claim_id.value

    @property
    def direct_link(self) -> DirectLink | None:
        return self.link if isinstance(self.link, DirectLink) else None


@dataclass(frozen=True, slots=True)
class ClaimRegistry:
    """Versioned, stable collection of persistent Claim decisions."""

    schema_version: str = CLAIM_REGISTRY_SCHEMA_VERSION
    entries: tuple[ClaimRegistryEntry, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != CLAIM_REGISTRY_SCHEMA_VERSION:
            raise ValueError(f"unsupported Claim registry schema: {self.schema_version!r}")
        if tuple(sorted(self.entries, key=registry_entry_sort_key)) != self.entries:
            raise ValueError("Claim registry entries must use stable Claim ID ordering")
        claim_ids = tuple(entry.claim_id for entry in self.entries)
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("Claim registry contains duplicate Claim IDs")

    def get(self, claim_id: str) -> ClaimRegistryEntry | None:
        return next((entry for entry in self.entries if entry.claim_id == claim_id), None)

    def with_entry(self, entry: ClaimRegistryEntry) -> ClaimRegistry:
        retained = tuple(item for item in self.entries if item.claim_id != entry.claim_id)
        return ClaimRegistry(
            schema_version=self.schema_version,
            entries=tuple(sorted((*retained, entry), key=registry_entry_sort_key)),
        )


def registry_entry_sort_key(entry: ClaimRegistryEntry) -> str:
    return entry.claim_id
