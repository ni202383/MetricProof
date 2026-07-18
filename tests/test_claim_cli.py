"""Stage 4B2a scan CLI and schema behavior."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metricproof.application.errors import ExitCode
from metricproof.cli import main as cli_main

runner = CliRunner()


def _project(root: Path, paper_text: str) -> None:
    paper = root / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(paper_text, encoding="utf-8")
    config = root / ".metricproof" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        'schema_version: "1"\npaper_paths: [paper/main.tex]\n',
        encoding="utf-8",
    )


def test_scan_help_exposes_claim_review_mode() -> None:
    result = runner.invoke(cli_main.app, ["scan", "--help"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "--show-claims" in result.stdout
    assert "likely and possible" in result.stdout


def test_scan_summary_and_claim_views_are_review_oriented(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project(
        tmp_path,
        r"Accuracy reaches 87.2\%. \setcounter{page}{7} Training uses 100 epochs.",
    )
    monkeypatch.chdir(tmp_path)

    summary = runner.invoke(cli_main.app, ["scan"])
    assert summary.exit_code == ExitCode.SUCCESS
    assert "1 likely" in summary.stdout
    assert "1 possible" in summary.stdout
    assert "1 non-experiment" in summary.stdout
    assert "MetricProof Claim candidate classifications" not in summary.stdout

    review = runner.invoke(cli_main.app, ["scan", "--show-claims"])
    assert review.exit_code == ExitCode.SUCCESS
    assert "MetricProof Claim candidate classifications" in review.stdout
    assert "87.2" in review.stdout
    assert "100" in review.stdout
    assert "CC_LAYOUT_ARGUMENT" not in review.stdout
    assert "non_experiment" not in review.stdout

    all_items = runner.invoke(cli_main.app, ["scan", "--show-all"])
    assert all_items.exit_code == ExitCode.SUCCESS
    assert "non_experiment" in all_items.stdout
    assert "CC_LAYOUT_ARGUMENT" in all_items.stdout


def test_scan_json_schema_three_retains_raw_candidates_and_classifications(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _project(tmp_path, r"Accuracy reaches 87.2\%. \setcounter{page}{7}")
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(cli_main.app, ["scan", "--json"])
    second = runner.invoke(cli_main.app, ["scan", "--json"])
    assert first.exit_code == ExitCode.SUCCESS
    assert first.stdout == second.stdout
    assert first.stderr == ""
    payload = json.loads(first.stdout)
    assert payload["schema_version"] == "3"
    assert payload["result_type"] == "paper_scan"
    assert len(payload["candidates"]) == 2
    assert len(payload["claim_classifications"]) == 2
    assert [item["candidate_index"] for item in payload["claim_classifications"]] == [0, 1]
    assert payload["summary"]["likely_claim_count"] == 1
    assert payload["summary"]["non_experiment_claim_count"] == 1
    assert "stable_claim_id" not in first.stdout
    assert payload["claim_classifications"][0]["evidence"][0]["reason_code"]
