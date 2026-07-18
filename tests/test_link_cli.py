"""End-user Claim link workflow tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from metricproof.adapters.claim_registry import YamlClaimRegistryRepository
from metricproof.application.errors import ExitCode
from metricproof.cli.main import app
from metricproof.domain.links import DerivedLink, DirectLink
from metricproof.domain.registry import ClaimRegistryStatus

runner = CliRunner()


def _write_direct_project(root: Path, *, matching_metric: bool = True) -> None:
    paper = root / "paper"
    runs = root / "runs"
    marker = root / ".metricproof"
    paper.mkdir()
    runs.mkdir()
    marker.mkdir()
    (paper / "main.tex").write_text(r"Accuracy reaches 87.2\%.", encoding="utf-8")
    metric_name = "accuracy" if matching_metric else "latency"
    metric_value = "0.872" if matching_metric else "4.2"
    (runs / "result.json").write_text(
        json.dumps({"metrics": {metric_name: metric_value}}),
        encoding="utf-8",
    )
    (marker / "config.yml").write_text(
        f"""schema_version: "1"
paper_paths: [paper/main.tex]
result_paths:
  - path: runs/result.json
    format: json
    run_id: proposed
    structured:
      metrics:
        {metric_name}: metrics.{metric_name}
""",
        encoding="utf-8",
    )


def _write_derived_project(root: Path) -> None:
    paper = root / "paper"
    runs = root / "runs"
    marker = root / ".metricproof"
    paper.mkdir()
    runs.mkdir()
    marker.mkdir()
    (paper / "main.tex").write_text(
        "Accuracy improves from 0.70 to 0.80, an improvement of 0.10.",
        encoding="utf-8",
    )
    (runs / "baseline.json").write_text('{"metrics":{"accuracy":"0.70"}}', encoding="utf-8")
    (runs / "proposed.json").write_text('{"metrics":{"accuracy":"0.80"}}', encoding="utf-8")
    (marker / "config.yml").write_text(
        """schema_version: "1"
paper_paths: [paper/main.tex]
result_paths:
  - path: runs/baseline.json
    format: json
    run_id: baseline
    structured:
      metrics: {accuracy: metrics.accuracy}
  - path: runs/proposed.json
    format: json
    run_id: proposed
    structured:
      metrics: {accuracy: metrics.accuracy}
""",
        encoding="utf-8",
    )


def _link_payload(root: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.chdir(root)
    result = runner.invoke(app, ["link", "--non-interactive", "--json"])
    assert result.exit_code == ExitCode.SUCCESS, result.output
    return cast(dict[str, Any], json.loads(result.stdout))


def test_non_interactive_json_is_stable_explainable_and_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    before_paper = (tmp_path / "paper" / "main.tex").read_bytes()
    before_result = (tmp_path / "runs" / "result.json").read_bytes()
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(app, ["link", "--non-interactive", "--json"])
    second = runner.invoke(app, ["link", "--non-interactive", "--json"])

    assert first.exit_code == ExitCode.SUCCESS
    assert first.stdout == second.stdout
    assert first.stderr == ""
    payload = json.loads(first.stdout)
    assert payload["schema_version"] == "1"
    assert payload["write_performed"] is False
    assert payload["summary"]["unlinked_count"] == 1
    candidate = payload["claims"][0]["candidates"][0]
    assert candidate["type"] == "direct"
    assert candidate["features"]
    assert candidate["uncertainties"]
    assert not (tmp_path / ".metricproof" / "claims.yml").exists()
    assert (tmp_path / "paper" / "main.tex").read_bytes() == before_paper
    assert (tmp_path / "runs" / "result.json").read_bytes() == before_result


def test_interactive_direct_confirmation_writes_once_and_rerun_does_not_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    linked = runner.invoke(app, ["link"], input="1\n\ny\n\n")

    assert linked.exit_code == ExitCode.SUCCESS, linked.output
    assert "Saved 1 confirmed decision" in linked.stdout
    path = tmp_path / ".metricproof" / "claims.yml"
    first_bytes = path.read_bytes()
    registry = YamlClaimRegistryRepository().load(tmp_path, ".metricproof/claims.yml")
    assert len(registry.entries) == 1
    assert registry.entries[0].status is ClaimRegistryStatus.ACTIVE
    assert isinstance(registry.entries[0].link, DirectLink)
    assert registry.entries[0].link.metric.metric_name == "accuracy"

    rerun = runner.invoke(app, ["link"])

    assert rerun.exit_code == ExitCode.SUCCESS
    assert "No Claims match" in rerun.stdout
    assert path.read_bytes() == first_bytes


def test_cancel_after_review_never_creates_registry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["link"], input="q\n")

    assert result.exit_code == ExitCode.SUCCESS
    assert "cancelled" in result.stdout
    assert not (tmp_path / ".metricproof" / "claims.yml").exists()


def test_interactive_ignore_is_persistent_and_not_reviewed_again(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    ignored = runner.invoke(
        app,
        ["link"],
        input="i\nreviewed as narrative context\ny\n\n",
    )

    assert ignored.exit_code == ExitCode.SUCCESS, ignored.output
    registry = YamlClaimRegistryRepository().load(tmp_path, ".metricproof/claims.yml")
    assert registry.entries[0].status is ClaimRegistryStatus.IGNORED
    assert registry.entries[0].ignore is not None
    assert registry.entries[0].ignore.note == "reviewed as narrative context"
    again = runner.invoke(app, ["link"])
    assert "No Claims match" in again.stdout


def test_manual_metric_selection_works_when_no_candidate_meets_threshold(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path, matching_metric=False)
    monkeypatch.chdir(tmp_path)

    payload = json.loads(runner.invoke(app, ["link", "--non-interactive", "--json"]).stdout)
    assert payload["claims"][0]["candidates"] == []

    linked = runner.invoke(app, ["link"], input="m\n1\n\ny\n\n")

    assert linked.exit_code == ExitCode.SUCCESS, linked.output
    registry = YamlClaimRegistryRepository().load(tmp_path, ".metricproof/claims.yml")
    assert isinstance(registry.entries[0].link, DirectLink)
    assert registry.entries[0].link.metric.metric_name == "latency"


def test_clear_derived_candidate_can_be_confirmed_as_bounded_derived_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_derived_project(tmp_path)
    payload = _link_payload(tmp_path, monkeypatch)
    target = next(item for item in payload["claims"] if item["raw_text"] == "0.10")
    derived_index = next(
        index
        for index, candidate in enumerate(target["candidates"], start=1)
        if candidate["type"] == "derived"
    )

    result = runner.invoke(
        app,
        ["link", "--claim", target["claim_id"]],
        input=f"{derived_index}\n\ny\n\n",
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    registry = YamlClaimRegistryRepository().load(tmp_path, ".metricproof/claims.yml")
    assert len(registry.entries) == 1
    assert isinstance(registry.entries[0].link, DerivedLink)
    assert registry.entries[0].link.operation.value == "subtraction"
    assert tuple(item.name for item in registry.entries[0].link.operands) == (
        "baseline",
        "candidate",
    )


def test_existing_active_link_requires_explicit_replace_confirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    payload = _link_payload(tmp_path, monkeypatch)
    claim_id = payload["claims"][0]["claim_id"]
    assert runner.invoke(app, ["link"], input="1\n\ny\n\n").exit_code == ExitCode.SUCCESS
    path = tmp_path / ".metricproof" / "claims.yml"
    before = path.read_bytes()

    result = runner.invoke(app, ["link", "--claim", claim_id], input="n\n")

    assert result.exit_code == ExitCode.SUCCESS
    assert "already has an active link" in result.stdout
    assert path.read_bytes() == before


def test_show_broken_exposes_retained_link_without_silent_deletion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["link"], input="1\n\ny\n\n").exit_code == ExitCode.SUCCESS
    repository = YamlClaimRegistryRepository()
    registry = repository.load(tmp_path, ".metricproof/claims.yml")
    entry = registry.entries[0]
    assert isinstance(entry.link, DirectLink)
    broken_link = replace(
        entry.link,
        metric=replace(entry.link.metric, source_selector="metrics.missing"),
    )
    repository.save(
        tmp_path,
        ".metricproof/claims.yml",
        registry.with_entry(replace(entry, link=broken_link)),
    )

    hidden = runner.invoke(app, ["link", "--non-interactive"])
    shown = runner.invoke(app, ["link", "--non-interactive", "--show-broken"])

    assert hidden.exit_code == ExitCode.SUCCESS
    assert "No Claims match" in hidden.stdout
    assert shown.exit_code == ExitCode.SUCCESS
    assert "broken" in shown.stdout
    retained = repository.load(tmp_path, ".metricproof/claims.yml")
    assert retained.entries[0].link == broken_link


def test_front_insertion_migrates_existing_link_without_new_unlinked_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(app, ["link"], input="1\n\ny\n\n").exit_code == ExitCode.SUCCESS
    registry = YamlClaimRegistryRepository().load(tmp_path, ".metricproof/claims.yml")
    stable_id = registry.entries[0].claim_id
    paper = tmp_path / "paper" / "main.tex"
    paper.write_text("Introductory text.\n" + paper.read_text(encoding="utf-8"), encoding="utf-8")

    result = runner.invoke(app, ["link", "--non-interactive", "--json"])

    assert result.exit_code == ExitCode.SUCCESS
    payload = json.loads(result.stdout)
    item = next(item for item in payload["claims"] if item["claim_id"] == stable_id)
    assert item["status"] == "active"
    assert item["migration"]["status"] in {"exact", "migrated"}
    assert payload["summary"]["unlinked_count"] == 0


def test_unknown_claim_and_malformed_registry_have_clean_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_direct_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    missing = runner.invoke(app, ["link", "--claim", "clm_00000000000000000000", "--json"])
    assert missing.exit_code == ExitCode.USAGE_ERROR
    missing_payload = json.loads(missing.stdout)
    assert missing_payload["error"]["code"] == "MPL_CLAIM_NOT_FOUND"
    assert missing.stderr == ""

    (tmp_path / ".metricproof" / "claims.yml").write_text(
        "schema_version: '1'\nclaims: [\n", encoding="utf-8"
    )
    malformed = runner.invoke(app, ["link", "--non-interactive", "--json"])
    assert malformed.exit_code == ExitCode.INPUT_ERROR
    malformed_payload = json.loads(malformed.stdout)
    assert malformed_payload["ok"] is False
    assert malformed_payload["error"]["code"] == "MP_LINK_INPUT"
    assert "Traceback" not in malformed.output
