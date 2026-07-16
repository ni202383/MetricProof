"""Safety-boundary tests for the local doctor adapter."""

import subprocess
from pathlib import Path, PureWindowsPath

import pytest

from metricproof.adapters import doctor as doctor_adapter
from metricproof.adapters.doctor import (
    MAX_SCAN_DEPTH,
    LocalDoctorProbe,
    is_ignored_relative_path,
)


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_latex_discovery_ignores_git_and_virtualenv(tmp_path: Path) -> None:
    visible = tmp_path / "paper" / "main.tex"
    ignored_venv = tmp_path / ".venv" / "hidden.tex"
    ignored_git = tmp_path / ".git" / "hidden.tex"
    for path in (visible, ignored_venv, ignored_git):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("content", encoding="utf-8")

    discovery = LocalDoctorProbe().find_latex_files(tmp_path)

    assert discovery.files == (visible,)
    assert not discovery.truncated
    assert not discovery.errors


def test_latex_discovery_respects_depth_boundary(tmp_path: Path) -> None:
    current = tmp_path
    for index in range(MAX_SCAN_DEPTH + 1):
        current = current / f"level-{index}"
    current.mkdir(parents=True)
    too_deep = current / "deep.tex"
    too_deep.write_text("content", encoding="utf-8")

    discovery = LocalDoctorProbe().find_latex_files(tmp_path)

    assert too_deep not in discovery.files


def test_doctor_adapter_does_not_modify_files(tmp_path: Path) -> None:
    latex_file = tmp_path / "paper.tex"
    latex_file.write_text("\\documentclass{article}", encoding="utf-8")
    config_dir = tmp_path / ".metricproof"
    config_dir.mkdir()
    before = _snapshot(tmp_path)

    probe = LocalDoctorProbe()
    assert probe.has_metricproof_directory(tmp_path)
    probe.find_project_root(tmp_path, None)
    probe.find_latex_files(tmp_path)

    assert _snapshot(tmp_path) == before


def test_project_root_can_be_found_from_metricproof_marker(tmp_path: Path) -> None:
    root = tmp_path / "project"
    nested = root / "paper" / "sections"
    nested.mkdir(parents=True)
    (root / ".metricproof").mkdir()

    assert LocalDoctorProbe().find_project_root(nested, None) == root


def test_windows_style_ignored_path_logic() -> None:
    assert is_ignored_relative_path(PureWindowsPath(r".venv\paper\hidden.tex"))
    assert is_ignored_relative_path(PureWindowsPath(r"project\.GIT\objects\data.tex"))
    assert not is_ignored_relative_path(PureWindowsPath(r"paper\sections\main.tex"))


def test_git_probe_reports_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git"], returncode=0, stdout=str(tmp_path), stderr=""
        )

    monkeypatch.setattr(doctor_adapter.subprocess, "run", fake_run)
    inspection = LocalDoctorProbe().inspect_git(tmp_path)

    assert inspection.state is doctor_adapter.GitState.REPOSITORY
    assert inspection.root == tmp_path.resolve()


def test_git_probe_reports_non_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )

    monkeypatch.setattr(doctor_adapter.subprocess, "run", fake_run)
    inspection = LocalDoctorProbe().inspect_git(tmp_path)

    assert inspection.state is doctor_adapter.GitState.NOT_REPOSITORY


@pytest.mark.parametrize(
    ("error", "expected_state"),
    [
        (FileNotFoundError(), doctor_adapter.GitState.UNAVAILABLE),
        (subprocess.TimeoutExpired(cmd="git", timeout=3), doctor_adapter.GitState.TIMEOUT),
        (OSError("blocked"), doctor_adapter.GitState.ERROR),
    ],
)
def test_git_probe_controls_process_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: OSError | subprocess.TimeoutExpired,
    expected_state: doctor_adapter.GitState,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise error

    monkeypatch.setattr(doctor_adapter.subprocess, "run", fake_run)
    assert LocalDoctorProbe().inspect_git(tmp_path).state is expected_state


def test_git_probe_controls_unexpected_git_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["git"], returncode=2, stdout="", stderr="bad usage"
        )

    monkeypatch.setattr(doctor_adapter.subprocess, "run", fake_run)
    inspection = LocalDoctorProbe().inspect_git(tmp_path)

    assert inspection.state is doctor_adapter.GitState.ERROR
    assert inspection.detail == "bad usage"


def test_project_root_accepts_containing_git_root(tmp_path: Path) -> None:
    nested = tmp_path / "paper" / "sections"
    nested.mkdir(parents=True)
    assert LocalDoctorProbe().find_project_root(nested, tmp_path) == tmp_path


def test_project_root_recognizes_metricproof_source_checkout(tmp_path: Path) -> None:
    nested = tmp_path / "src" / "metricproof"
    nested.mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text("[project]", encoding="utf-8")
    assert LocalDoctorProbe().find_project_root(nested, None) == tmp_path


def test_latex_discovery_reports_invalid_root(tmp_path: Path) -> None:
    discovery = LocalDoctorProbe().find_latex_files(tmp_path / "missing")
    assert discovery.errors
    assert not discovery.files


def test_latex_discovery_reports_truncation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(doctor_adapter, "MAX_SCAN_FILES", 2)
    for index in range(3):
        (tmp_path / f"paper-{index}.tex").write_text("content", encoding="utf-8")

    discovery = LocalDoctorProbe().find_latex_files(tmp_path)

    assert discovery.truncated
    assert len(discovery.files) == 2
