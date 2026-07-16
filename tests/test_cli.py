"""End-user CLI tests."""

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metricproof.application.doctor import GitInspection, GitState, LatexDiscovery
from metricproof.application.errors import ExitCode, MetricProofError
from metricproof.cli import main as cli_main

runner = CliRunner()


@dataclass
class CliProbe:
    root: Path
    version: tuple[int, int, int] = (3, 13, 0)

    def python_version(self) -> tuple[int, int, int]:
        return self.version

    def inspect_git(self, current_directory: Path) -> GitInspection:
        return GitInspection(GitState.REPOSITORY, root=self.root)

    def find_project_root(self, current_directory: Path, git_root: Path | None) -> Path | None:
        return self.root

    def has_metricproof_directory(self, project_root: Path) -> bool:
        return False

    def find_latex_files(self, project_root: Path) -> LatexDiscovery:
        return LatexDiscovery(())


def test_help() -> None:
    result = runner.invoke(cli_main.app, ["--help"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "doctor" in result.output
    assert "--version" in result.output


def test_version_uses_package_version() -> None:
    result = runner.invoke(cli_main.app, ["--version"])
    assert result.exit_code == ExitCode.SUCCESS
    assert result.output.strip() == "MetricProof 0.1.0.dev0"


def test_doctor_command_renders_structured_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli_main, "_build_doctor_probe", lambda: CliProbe(tmp_path))

    result = runner.invoke(cli_main.app, ["doctor"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "MetricProof doctor" in result.output
    assert "MPD001" in result.output
    assert "PASS" in result.output
    assert "WARN" in result.output


def test_doctor_command_maps_failed_check_to_environment_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    probe = CliProbe(tmp_path, version=(3, 12, 0))
    monkeypatch.setattr(cli_main, "_build_doctor_probe", lambda: probe)

    result = runner.invoke(cli_main.app, ["doctor"])

    assert result.exit_code == ExitCode.ENVIRONMENT_ERROR
    assert "MPD001" in result.output
    assert "FAIL" in result.output


def test_expected_error_is_written_to_stderr_without_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_expected_error() -> CliProbe:
        raise MetricProofError("invalid local configuration", ExitCode.INPUT_ERROR)

    monkeypatch.setattr(cli_main, "_build_doctor_probe", raise_expected_error)
    result = runner.invoke(cli_main.app, ["doctor"])

    assert result.exit_code == ExitCode.INPUT_ERROR
    assert "MP_ERROR: invalid local configuration" in result.stderr
    assert "Traceback" not in result.output
    assert result.stdout == ""


def test_unexpected_error_is_hidden_without_traceback(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_unexpected_error() -> CliProbe:
        raise RuntimeError("secret third-party detail")

    monkeypatch.setattr(cli_main, "_build_doctor_probe", raise_unexpected_error)
    result = runner.invoke(cli_main.app, ["doctor"])

    assert result.exit_code == ExitCode.INTERNAL_ERROR
    assert "MP_INTERNAL" in result.stderr
    assert "secret third-party detail" not in result.output
    assert "Traceback" not in result.output


def test_python_module_help(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    environment = os.environ.copy()
    existing_pythonpath = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        str(source_root)
        if not existing_pythonpath
        else f"{source_root}{os.pathsep}{existing_pythonpath}"
    )

    completed = subprocess.run(
        [sys.executable, "-m", "metricproof", "--help"],
        cwd=tmp_path,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
    )

    assert completed.returncode == ExitCode.SUCCESS
    assert "doctor" in completed.stdout
    assert "Traceback" not in completed.stderr


def test_keyboard_interrupt_maps_to_130(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_interrupt() -> CliProbe:
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "_build_doctor_probe", raise_interrupt)
    result = runner.invoke(cli_main.app, ["doctor"])

    assert result.exit_code == ExitCode.INTERRUPTED
    assert "MP_INTERRUPTED" in result.stderr
    assert "Traceback" not in result.output


def test_invalid_command_uses_usage_exit_without_traceback() -> None:
    result = runner.invoke(cli_main.app, ["not-a-command"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "Traceback" not in result.output
