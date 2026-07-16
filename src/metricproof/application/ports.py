"""Ports required for project configuration and experiment input loading."""

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from metricproof.application.configuration import ExperimentSource, ProjectConfiguration
from metricproof.domain.models import ExperimentRun, InputDiagnostic
from metricproof.domain.paper import PaperScanResult


@dataclass(frozen=True, slots=True)
class SourceReadResult:
    runs: tuple[ExperimentRun, ...]
    diagnostics: tuple[InputDiagnostic, ...] = ()


class ConfigurationRepository(Protocol):
    def load(self, project_root: Path) -> ProjectConfiguration: ...


class ExperimentSourceReader(Protocol):
    def read(self, project_root: Path, source: ExperimentSource) -> SourceReadResult: ...


class PaperScanner(Protocol):
    def scan(
        self,
        project_root: Path,
        entry_paths: tuple[str, ...],
        exclude_paths: tuple[str, ...] = (),
    ) -> PaperScanResult: ...
