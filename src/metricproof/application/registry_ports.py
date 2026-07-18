"""Application boundary for strict Claim registry persistence."""

from pathlib import Path
from typing import Protocol

from metricproof.domain.registry import ClaimRegistry


class ClaimRegistryRepository(Protocol):
    def load(self, project_root: Path, registry_path: str) -> ClaimRegistry: ...

    def save(
        self,
        project_root: Path,
        registry_path: str,
        registry: ClaimRegistry,
    ) -> None: ...
