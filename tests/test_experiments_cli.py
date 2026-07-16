"""End-user experiments list/validate CLI tests."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metricproof.application.errors import ExitCode
from metricproof.cli.main import app

runner = CliRunner()


def _write_project(tmp_path: Path, *, invalid_json: bool = False) -> None:
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "result.json").write_text(
        '{"metrics":{"accuracy":true}}'
        if invalid_json
        else '{"metrics":{"accuracy":0.91},"meta":{"dataset":"cifar10"}}',
        encoding="utf-8",
    )
    config = tmp_path / ".metricproof" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        """schema_version: "1"
result_paths:
  - path: runs/result.json
    format: json
    run_id: baseline
    structured:
      metrics:
        accuracy: metrics.accuracy
      metadata:
        dataset: meta.dataset
""",
        encoding="utf-8",
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_experiments_help_is_available() -> None:
    result = runner.invoke(app, ["experiments", "--help"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "list" in result.output
    assert "validate" in result.output


def test_experiments_list_human_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["experiments", "list"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "MetricProof experiments" in result.stdout
    assert "baseline" in result.stdout
    assert "accuracy" in result.stdout
    assert "0.91" in result.stdout
    assert result.stderr == ""


def test_experiments_list_json_is_clean_and_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(app, ["experiments", "list", "--json"])
    second = runner.invoke(app, ["experiments", "list", "--json"])
    assert first.exit_code == ExitCode.SUCCESS
    assert first.stdout == second.stdout
    assert first.stderr == ""
    payload = json.loads(first.stdout)
    assert payload["ok"] is True
    assert payload["runs"][0]["run_id"] == "baseline"
    assert payload["runs"][0]["metrics"][0]["value"] == "0.91"


def test_experiments_validate_human_failure_uses_input_exit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, invalid_json=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["experiments", "validate"])
    assert result.exit_code == ExitCode.INPUT_ERROR
    assert "validation failed" in result.stdout
    assert "MPE_INVALID_NUMBER" in result.stderr
    assert "Traceback" not in result.output


def test_experiments_validate_json_failure_is_machine_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, invalid_json=True)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["experiments", "validate", "--json"])
    assert result.exit_code == ExitCode.INPUT_ERROR
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["diagnostics"][0]["code"] == "MPE_INVALID_NUMBER"
    assert payload["diagnostics"][0]["remediation"]


def test_missing_config_maps_to_usage_error_without_traceback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["experiments", "validate"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "MPC_CONFIG" in result.stderr
    assert result.stdout == ""
    assert "Traceback" not in result.output


def test_missing_config_json_error_stays_on_stdout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["experiments", "validate", "--json"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "MPC_CONFIG"


def test_empty_source_list_has_explicit_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / ".metricproof" / "config.yml"
    config.parent.mkdir()
    config.write_text('schema_version: "1"\nresult_paths: []\n', encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["experiments", "list"])
    assert result.exit_code == ExitCode.SUCCESS
    assert result.stdout.strip() == "No experiments were loaded."


def test_experiments_commands_do_not_modify_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    before = _snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["experiments", "list"]).exit_code == ExitCode.SUCCESS
    assert runner.invoke(app, ["experiments", "validate"]).exit_code == ExitCode.SUCCESS
    assert _snapshot(tmp_path) == before
