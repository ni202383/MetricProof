"""Application orchestration for controlled raw LaTeX numeric scanning."""

from __future__ import annotations

from pathlib import Path, PurePosixPath, PureWindowsPath

from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.application.ports import PaperScanner
from metricproof.domain.paper import PaperScanResult, PaperScanStatistics


def scan_paper(
    project_root: Path,
    configuration: ProjectConfiguration,
    scanner: PaperScanner,
    *,
    selected_file: str | None = None,
) -> PaperScanResult:
    """Scan configured entries and optionally select one existing graph document."""

    if not configuration.paper_paths:
        raise ProjectConfigurationError(
            file=".metricproof/config.yml",
            field="paper_paths",
            reason="at least one LaTeX entry file is required for scan",
            remediation="declare one or more project-relative .tex entry files",
        )
    result = scanner.scan(
        project_root,
        configuration.paper_paths,
        configuration.exclude_paths,
    )
    if selected_file is None:
        return result

    normalized = _normalize_selected_file(selected_file)
    graph_files = {document.path for document in result.graph.documents}
    if normalized not in graph_files:
        raise ProjectConfigurationError(
            file=".metricproof/config.yml",
            field="paper_paths",
            reason=f"--file is not part of the configured LaTeX graph: {selected_file!r}",
            remediation="choose a project-relative .tex file reported by metricproof scan",
        )
    candidates = tuple(
        candidate for candidate in result.candidates if candidate.location.path == normalized
    )
    return PaperScanResult(
        graph=result.graph,
        candidates=candidates,
        diagnostics=result.diagnostics,
        statistics=PaperScanStatistics(
            scanned_file_count=result.statistics.scanned_file_count,
            total_bytes=result.statistics.total_bytes,
            candidate_count=len(candidates),
            diagnostic_count=len(result.diagnostics),
        ),
        complete=result.complete,
    )


def _normalize_selected_file(value: str) -> str:
    if not value.strip():
        raise _selection_error(value, "path must not be empty")
    windows = PureWindowsPath(value)
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if windows.is_absolute() or path.is_absolute():
        raise _selection_error(value, "absolute paths are not allowed")
    if ".." in path.parts:
        raise _selection_error(value, "parent traversal is not allowed")
    if path.suffix.casefold() != ".tex":
        raise _selection_error(value, "only .tex graph files can be selected")
    return path.as_posix()


def _selection_error(value: str, reason: str) -> ProjectConfigurationError:
    return ProjectConfigurationError(
        file=".metricproof/config.yml",
        field="paper_paths",
        reason=f"invalid --file path {value!r}: {reason}",
        remediation="use a project-relative .tex file from the configured graph",
    )
