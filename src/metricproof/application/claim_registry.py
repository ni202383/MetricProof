"""Small application services for Claim registry load and atomic save."""

from pathlib import Path

from metricproof.application.registry_ports import ClaimRegistryRepository
from metricproof.domain.registry import ClaimRegistry, ClaimRegistryEntry


def load_claim_registry(
    project_root: Path,
    registry_path: str,
    repository: ClaimRegistryRepository,
) -> ClaimRegistry:
    return repository.load(project_root, registry_path)


def save_claim_registry(
    project_root: Path,
    registry_path: str,
    registry: ClaimRegistry,
    repository: ClaimRegistryRepository,
) -> None:
    repository.save(project_root, registry_path, registry)


def save_registry_entry(
    project_root: Path,
    registry_path: str,
    registry: ClaimRegistry,
    entry: ClaimRegistryEntry,
    repository: ClaimRegistryRepository,
) -> ClaimRegistry:
    updated = registry.with_entry(entry)
    repository.save(project_root, registry_path, updated)
    return updated
