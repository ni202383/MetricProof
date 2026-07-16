"""Application-level orchestration for non-destructive environment checks."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from metricproof.application.errors import ExitCode

MINIMUM_PYTHON = (3, 13)
MAXIMUM_PYTHON = (4, 0)


class DoctorStatus(StrEnum):
    """Severity-like status for a doctor check."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class GitState(StrEnum):
    """Controlled outcomes from the read-only Git probe."""

    REPOSITORY = "repository"
    NOT_REPOSITORY = "not_repository"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class GitInspection:
    """Result of checking whether a directory belongs to a Git repository."""

    state: GitState
    root: Path | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class LatexDiscovery:
    """Bounded result of locating LaTeX source files."""

    files: tuple[Path, ...]
    truncated: bool = False
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One user-visible, structured doctor diagnostic."""

    code: str
    status: DoctorStatus
    message: str
    location: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DoctorReport:
    """Ordered checks and their process-level outcome."""

    checks: tuple[DoctorCheck, ...]

    @property
    def exit_code(self) -> ExitCode:
        if any(check.status is DoctorStatus.FAIL for check in self.checks):
            return ExitCode.ENVIRONMENT_ERROR
        return ExitCode.SUCCESS


class DoctorProbe(Protocol):
    """Read-only environment boundary required by the doctor service."""

    def python_version(self) -> tuple[int, int, int]: ...

    def inspect_git(self, current_directory: Path) -> GitInspection: ...

    def find_project_root(self, current_directory: Path, git_root: Path | None) -> Path | None: ...

    def has_metricproof_directory(self, project_root: Path) -> bool: ...

    def find_latex_files(self, project_root: Path) -> LatexDiscovery: ...


def run_doctor(probe: DoctorProbe, current_directory: Path) -> DoctorReport:
    """Run deterministic checks without performing any writes."""

    current_directory = current_directory.resolve()
    checks: list[DoctorCheck] = []

    version = probe.python_version()
    version_pair = version[:2]
    supported = MINIMUM_PYTHON <= version_pair < MAXIMUM_PYTHON
    checks.append(
        DoctorCheck(
            code="MPD001",
            status=DoctorStatus.PASS if supported else DoctorStatus.FAIL,
            message=(
                "Python version satisfies >=3.13,<4.0."
                if supported
                else "Python version does not satisfy >=3.13,<4.0."
            ),
            location="python",
            evidence=(f"detected={'.'.join(str(part) for part in version)}",),
        )
    )

    git = probe.inspect_git(current_directory)
    if git.state is GitState.REPOSITORY:
        git_check = DoctorCheck(
            code="MPD002",
            status=DoctorStatus.PASS,
            message="Current directory is inside a Git repository.",
            location=str(current_directory),
            evidence=(f"git_root={git.root}",),
        )
    elif git.state is GitState.NOT_REPOSITORY:
        git_check = DoctorCheck(
            code="MPD002",
            status=DoctorStatus.WARN,
            message="Current directory is not inside a Git repository.",
            location=str(current_directory),
            evidence=(git.detail or "git rev-parse reported no repository",),
        )
    else:
        git_check = DoctorCheck(
            code="MPD002",
            status=DoctorStatus.FAIL,
            message="Git repository status could not be determined.",
            location=str(current_directory),
            evidence=(git.detail or f"git_state={git.state.value}",),
        )
    checks.append(git_check)

    project_root = probe.find_project_root(current_directory, git.root)
    scan_root = project_root or current_directory
    checks.append(
        DoctorCheck(
            code="MPD003",
            status=DoctorStatus.PASS if project_root is not None else DoctorStatus.WARN,
            message=(
                "Project root was identified."
                if project_root is not None
                else "Project root could not be identified; checks use the current directory."
            ),
            location=str(scan_root),
            evidence=(
                f"project_root={project_root}"
                if project_root is not None
                else "markers=.git,.metricproof,pyproject+src/metricproof",
            ),
        )
    )

    has_config = probe.has_metricproof_directory(scan_root)
    checks.append(
        DoctorCheck(
            code="MPD004",
            status=DoctorStatus.PASS if has_config else DoctorStatus.WARN,
            message=(
                ".metricproof directory is present."
                if has_config
                else ".metricproof directory is not present."
            ),
            location=str(scan_root / ".metricproof"),
            evidence=(f"exists={str(has_config).lower()}",),
        )
    )

    latex = probe.find_latex_files(scan_root)
    if latex.errors:
        latex_status = DoctorStatus.FAIL
        latex_message = "LaTeX discovery encountered filesystem errors."
    elif latex.files:
        latex_status = DoctorStatus.PASS
        latex_message = f"Found {len(latex.files)} LaTeX file(s) within the scan boundary."
    else:
        latex_status = DoctorStatus.WARN
        latex_message = "No LaTeX files were found within the scan boundary."

    relative_files = tuple(_display_relative(scan_root, path) for path in latex.files[:5])
    latex_evidence = (
        f"count={len(latex.files)}",
        f"truncated={str(latex.truncated).lower()}",
        *(f"file={path}" for path in relative_files),
        *(f"error={error}" for error in latex.errors),
    )
    checks.append(
        DoctorCheck(
            code="MPD005",
            status=latex_status,
            message=latex_message,
            location=str(scan_root),
            evidence=latex_evidence,
        )
    )

    return DoctorReport(checks=tuple(checks))


def _display_relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()
