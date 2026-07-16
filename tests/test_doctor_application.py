"""Pure application tests for doctor orchestration and exit codes."""

from dataclasses import dataclass, field
from pathlib import Path

from metricproof.application.doctor import (
    DoctorStatus,
    GitInspection,
    GitState,
    LatexDiscovery,
    run_doctor,
)
from metricproof.application.errors import ExitCode


@dataclass
class FakeProbe:
    root: Path | None
    version: tuple[int, int, int] = (3, 13, 0)
    git: GitInspection = field(
        default_factory=lambda: GitInspection(GitState.NOT_REPOSITORY, detail="not a repository")
    )
    has_config: bool = False
    latex: LatexDiscovery = field(default_factory=lambda: LatexDiscovery(()))

    def python_version(self) -> tuple[int, int, int]:
        return self.version

    def inspect_git(self, current_directory: Path) -> GitInspection:
        return self.git

    def find_project_root(self, current_directory: Path, git_root: Path | None) -> Path | None:
        return self.root

    def has_metricproof_directory(self, project_root: Path) -> bool:
        return self.has_config

    def find_latex_files(self, project_root: Path) -> LatexDiscovery:
        return self.latex


def _check_status(report_code: str, probe: FakeProbe, current: Path) -> DoctorStatus:
    report = run_doctor(probe, current)
    return next(check.status for check in report.checks if check.code == report_code)


def test_doctor_reports_git_repository(tmp_path: Path) -> None:
    probe = FakeProbe(
        root=tmp_path,
        git=GitInspection(GitState.REPOSITORY, root=tmp_path),
    )
    assert _check_status("MPD002", probe, tmp_path) is DoctorStatus.PASS


def test_doctor_reports_non_git_directory_without_exception(tmp_path: Path) -> None:
    probe = FakeProbe(root=None)
    report = run_doctor(probe, tmp_path)
    assert _check_status("MPD002", probe, tmp_path) is DoctorStatus.WARN
    assert report.exit_code is ExitCode.SUCCESS


def test_doctor_detects_metricproof_directory(tmp_path: Path) -> None:
    probe = FakeProbe(root=tmp_path, has_config=True)
    assert _check_status("MPD004", probe, tmp_path) is DoctorStatus.PASS


def test_doctor_reports_discovered_latex_file(tmp_path: Path) -> None:
    latex_file = tmp_path / "paper" / "main.tex"
    probe = FakeProbe(root=tmp_path, latex=LatexDiscovery((latex_file,)))
    report = run_doctor(probe, tmp_path)
    latex_check = next(check for check in report.checks if check.code == "MPD005")
    assert latex_check.status is DoctorStatus.PASS
    assert "file=paper/main.tex" in latex_check.evidence


def test_doctor_returns_environment_exit_code_for_failed_check(tmp_path: Path) -> None:
    probe = FakeProbe(root=tmp_path, version=(3, 12, 9))
    report = run_doctor(probe, tmp_path)
    assert report.exit_code is ExitCode.ENVIRONMENT_ERROR
    assert _check_status("MPD001", probe, tmp_path) is DoctorStatus.FAIL


def test_doctor_treats_git_unavailable_as_controlled_failure(tmp_path: Path) -> None:
    probe = FakeProbe(
        root=None,
        git=GitInspection(GitState.UNAVAILABLE, detail="git executable was not found"),
    )
    report = run_doctor(probe, tmp_path)
    assert report.exit_code is ExitCode.ENVIRONMENT_ERROR
    assert _check_status("MPD002", probe, tmp_path) is DoctorStatus.FAIL


def test_doctor_reports_latex_filesystem_errors(tmp_path: Path) -> None:
    probe = FakeProbe(
        root=tmp_path,
        latex=LatexDiscovery((), errors=("permission denied",)),
    )
    report = run_doctor(probe, tmp_path)
    assert report.exit_code is ExitCode.ENVIRONMENT_ERROR
    assert _check_status("MPD005", probe, tmp_path) is DoctorStatus.FAIL


def test_doctor_preserves_outside_file_as_absolute_evidence(tmp_path: Path) -> None:
    outside_file = tmp_path.parent / "outside.tex"
    probe = FakeProbe(root=tmp_path, latex=LatexDiscovery((outside_file,)))
    report = run_doctor(probe, tmp_path)
    latex_check = next(check for check in report.checks if check.code == "MPD005")
    assert f"file={outside_file.as_posix()}" in latex_check.evidence


def test_doctor_rejects_python_4(tmp_path: Path) -> None:
    probe = FakeProbe(root=tmp_path, version=(4, 0, 0))
    report = run_doctor(probe, tmp_path)
    assert report.exit_code is ExitCode.ENVIRONMENT_ERROR
    assert _check_status("MPD001", probe, tmp_path) is DoctorStatus.FAIL
