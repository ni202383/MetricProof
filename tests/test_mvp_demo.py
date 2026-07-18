"""The checked-in MVP demo remains runnable and intentionally mixed."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from metricproof.application.errors import ExitCode
from metricproof.cli.main import app


def test_mvp_demo_proves_consistent_ignored_and_three_diagnostic_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1] / "examples" / "mvp-demo"
    tracked_inputs = tuple(
        sorted(
            (
                root / ".metricproof" / "config.yml",
                root / ".metricproof" / "claims.yml",
                root / "paper" / "main.tex",
                root / "runs" / "results.yml",
            )
        )
    )
    before = {path: path.read_bytes() for path in tracked_inputs}
    monkeypatch.chdir(root)

    completed = CliRunner().invoke(app, ["check", "--json"])

    assert completed.exit_code == ExitCode.ANALYSIS_FAILURE, completed.stdout
    payload = cast(dict[str, Any], json.loads(completed.stdout))
    assert [item["code"] for item in payload["diagnostics"]] == [
        "STALE_VALUE",
        "WRONG_DELTA",
        "MISSING_PROVENANCE",
    ]
    assert payload["summary"]["checked_claim_count"] == 6
    assert payload["summary"]["registry"] == {
        "active": 4,
        "ignored": 1,
        "unlinked": 1,
    }
    assert payload["summary"]["diagnostics_by_severity"] == {
        "error": 2,
        "warning": 1,
    }
    assert payload["diagnostics"][0]["observed"] == "0.800"
    assert payload["diagnostics"][0]["expected"] == "0.90"
    assert payload["diagnostics"][1]["observed"] == "25.0"
    assert payload["diagnostics"][1]["expected"] == "20.0"
    assert {path: path.read_bytes() for path in tracked_inputs} == before


def test_mvp_demo_links_migrate_after_front_matter_insertion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = Path(__file__).resolve().parents[1] / "examples" / "mvp-demo"
    project = tmp_path / "mvp-demo"
    shutil.copytree(source, project)
    paper = project / "paper" / "main.tex"
    paper.write_text(
        "% Added front matter that changes every absolute line and character offset.\n"
        + paper.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.chdir(project)

    completed = CliRunner().invoke(app, ["check", "--json"])

    assert completed.exit_code == ExitCode.ANALYSIS_FAILURE, completed.stdout
    payload = cast(dict[str, Any], json.loads(completed.stdout))
    assert payload["summary"]["registry"] == {
        "active": 4,
        "ignored": 1,
        "unlinked": 1,
    }
    assert payload["summary"]["migrations"] == {"migrated": 5}
    assert not {
        "LINK_CLAIM_AMBIGUOUS",
        "LINK_CLAIM_MISSING",
    } & {item["code"] for item in payload["diagnostics"]}
