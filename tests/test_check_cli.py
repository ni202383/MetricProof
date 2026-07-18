"""Unified CheckResult and metricproof check end-to-end tests."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from metricproof.adapters.claim_registry import YamlClaimRegistryRepository
from metricproof.adapters.config import YamlConfigurationRepository
from metricproof.adapters.experiments import LocalExperimentSourceReader
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.application.claim_identity import prepare_claim_identities
from metricproof.application.errors import ExitCode
from metricproof.application.experiments import load_experiments
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.cli.main import app
from metricproof.domain.claim_identity import ClaimIdentitySnapshot, IdentifiedClaim
from metricproof.domain.links import (
    DerivedLink,
    DerivedOperand,
    DerivedOperation,
    DirectLink,
    LinkScale,
    MetricReference,
    RoundingPolicy,
)
from metricproof.domain.models import MetricObservation, NumericUnit
from metricproof.domain.registry import (
    ClaimRegistry,
    ClaimRegistryEntry,
    ClaimRegistryStatus,
    IgnoreReason,
    IgnoreRecord,
)

runner = CliRunner()


def _write_project(root: Path, *, policy: str = "") -> None:
    (root / "paper").mkdir()
    (root / "runs").mkdir()
    (root / ".metricproof").mkdir()
    (root / "paper" / "main.tex").write_text(
        "\n".join(
            (
                r"Accuracy reaches 80.0\%.",
                "Accuracy improvement is 0.25.",
                "F1 reaches 0.75.",
                "Latency reaches 10.0.",
                "Recall reaches 0.60.",
            )
        ),
        encoding="utf-8",
    )
    (root / "runs" / "baseline.json").write_text(
        '{"metrics":{"accuracy":"0.70"}}',
        encoding="utf-8",
    )
    (root / "runs" / "proposed.json").write_text(
        '{"metrics":{"accuracy":"0.90","f1":"0.75","latency":"10.0","recall":"0.60"}}',
        encoding="utf-8",
    )
    policy_block = f"\npolicy:\n{policy}" if policy else ""
    (root / ".metricproof" / "config.yml").write_text(
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
      metrics:
        accuracy: metrics.accuracy
        f1: metrics.f1
        latency: metrics.latency
        recall: metrics.recall
"""
        + policy_block
        + "\n",
        encoding="utf-8",
    )


def _prepare_registry(root: Path) -> ClaimRegistry:
    configuration = YamlConfigurationRepository().load(root)
    scan = LocalLatexPaperScanner().scan(root, configuration.paper_paths)
    claims = prepare_claim_identities(scan, configuration).identities.claims
    catalog = load_experiments(root, configuration, LocalExperimentSourceReader())
    by_text = {claim.raw_text: claim for claim in claims}

    stale_claim = by_text[r"80.0\%"]
    improvement_claim = by_text["0.25"]
    ignored_claim = by_text["10.0"]
    normal_claim = by_text["0.60"]
    proposed_accuracy = _observation(catalog.observations, "proposed", "accuracy")
    baseline_accuracy = _observation(catalog.observations, "baseline", "accuracy")
    recall = _observation(catalog.observations, "proposed", "recall")

    entries = (
        _direct_entry(stale_claim, proposed_accuracy),
        _derived_entry(improvement_claim, baseline_accuracy, proposed_accuracy),
        ClaimRegistryEntry(
            identity=ClaimIdentitySnapshot.from_claim(ignored_claim),
            status=ClaimRegistryStatus.IGNORED,
            ignore=IgnoreRecord(IgnoreReason.USER_DECISION, "reviewed non-target metric"),
        ),
        _direct_entry(normal_claim, recall),
    )
    registry = ClaimRegistry(entries=tuple(sorted(entries, key=lambda item: item.claim_id)))
    YamlClaimRegistryRepository().save(root, ".metricproof/claims.yml", registry)
    return registry


def _direct_entry(
    claim: IdentifiedClaim,
    observation: MetricObservation,
) -> ClaimRegistryEntry:
    return ClaimRegistryEntry(
        identity=ClaimIdentitySnapshot.from_claim(claim),
        status=ClaimRegistryStatus.ACTIVE,
        link=DirectLink(
            claim_id=claim.claim_id,
            metric=_reference(observation),
            confirmed_fingerprint=claim.fingerprint.digest,
        ),
    )


def _derived_entry(
    claim: IdentifiedClaim,
    baseline: MetricObservation,
    candidate: MetricObservation,
) -> ClaimRegistryEntry:
    return ClaimRegistryEntry(
        identity=ClaimIdentitySnapshot.from_claim(claim),
        status=ClaimRegistryStatus.ACTIVE,
        link=DerivedLink(
            claim_id=claim.claim_id,
            operation=DerivedOperation.SUBTRACTION,
            operands=(
                DerivedOperand("baseline", _reference(baseline)),
                DerivedOperand("candidate", _reference(candidate)),
            ),
            output_unit=NumericUnit.SCALAR,
            output_scale=LinkScale.IDENTITY,
            confirmed_fingerprint=claim.fingerprint.digest,
            rounding=RoundingPolicy(decimal_places=2),
        ),
    )


def _reference(observation: MetricObservation) -> MetricReference:
    return MetricReference(
        source_file=observation.source_file,
        run_id=observation.run_id,
        metric_name=observation.metric_name,
        source_selector=observation.source_selector,
    )


def _observation(
    observations: tuple[MetricObservation, ...],
    run_id: str,
    metric_name: str,
) -> MetricObservation:
    return next(
        item for item in observations if item.run_id == run_id and item.metric_name == metric_name
    )


def _json_result(*args: str) -> tuple[int, dict[str, Any], str]:
    completed = runner.invoke(app, ["check", "--json", *args])
    return (
        completed.exit_code,
        cast(dict[str, Any], json.loads(completed.stdout)),
        completed.stderr,
    )


def _snapshot_inputs(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for directory in (root / "paper", root / "runs")
        for path in directory.rglob("*")
        if path.is_file()
    }


def test_check_reports_three_rules_and_preserves_ignored_and_normal_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    registry = _prepare_registry(tmp_path)
    before = _snapshot_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)

    terminal = runner.invoke(app, ["check"])
    json_exit, payload, stderr = _json_result()

    assert terminal.exit_code == ExitCode.ANALYSIS_FAILURE
    assert json_exit == ExitCode.ANALYSIS_FAILURE
    assert stderr == ""
    assert "MetricProof CheckResult diagnostics" in terminal.stdout
    codes = [item["code"] for item in payload["diagnostics"]]
    assert codes == ["STALE_VALUE", "WRONG_DELTA", "MISSING_PROVENANCE"]
    assert all(code in terminal.stdout for code in codes)
    assert payload["summary"]["registry"] == {
        "active": 3,
        "ignored": 1,
        "unlinked": 1,
    }
    assert payload["summary"]["checked_claim_count"] == 5
    assert payload["tool_version"]
    assert payload["project"] == tmp_path.name
    assert payload["ok"] is False
    assert len(registry.entries) == 4
    assert _snapshot_inputs(tmp_path) == before


def test_check_json_is_byte_stable_and_has_complete_review_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    _prepare_registry(tmp_path)
    monkeypatch.chdir(tmp_path)

    first = runner.invoke(app, ["check", "--json"])
    second = runner.invoke(app, ["check", "--json"])

    assert first.exit_code == second.exit_code == ExitCode.ANALYSIS_FAILURE
    assert first.stdout == second.stdout
    assert first.stderr == second.stderr == ""
    payload = cast(dict[str, Any], json.loads(first.stdout))
    for diagnostic in payload["diagnostics"]:
        assert diagnostic["diagnostic_id"].startswith("diag_")
        assert diagnostic["claim_id"].startswith("clm_")
        assert diagnostic["location"]["path"] == "paper/main.tex"
        assert diagnostic["observed"] is not None
        assert diagnostic["expected"] is not None
        assert diagnostic["confidence"]
        assert diagnostic["evidence"]
        assert diagnostic["remediation"]
        assert diagnostic["uncertainties"]


def test_rule_filter_and_fail_threshold_control_only_rule_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    _prepare_registry(tmp_path)
    monkeypatch.chdir(tmp_path)

    default_exit, default_payload, _ = _json_result("--rule", "MISSING_PROVENANCE")
    warning_exit, warning_payload, _ = _json_result(
        "--rule",
        "MISSING_PROVENANCE",
        "--fail-on",
        "warning",
    )
    stale_exit, stale_payload, _ = _json_result("--rule", "stale_value")

    assert default_exit == ExitCode.SUCCESS
    assert default_payload["ok"] is True
    assert [item["code"] for item in default_payload["diagnostics"]] == ["MISSING_PROVENANCE"]
    assert warning_exit == ExitCode.ANALYSIS_FAILURE
    assert warning_payload["fail_on"] == "warning"
    assert stale_exit == ExitCode.ANALYSIS_FAILURE
    assert [item["code"] for item in stale_payload["diagnostics"]] == ["STALE_VALUE"]


def test_invalid_rule_and_fail_on_are_clean_usage_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)

    skipped_rule = runner.invoke(app, ["check", "--json", "--rule", "WRONG_BEST_MARK"])
    bad_rule = runner.invoke(app, ["check", "--json", "--rule", "NOT_A_RULE"])
    bad_threshold = runner.invoke(app, ["check", "--json", "--fail-on", "info"])

    assert skipped_rule.exit_code == ExitCode.SUCCESS
    skipped_payload = json.loads(skipped_rule.stdout)
    assert skipped_payload["summary"]["rules"][3]["status"] == "skipped"
    assert bad_rule.exit_code == ExitCode.USAGE_ERROR
    assert json.loads(bad_rule.stdout)["error"]["code"] == "MPC_RULE"
    assert bad_rule.stderr == ""
    assert bad_threshold.exit_code == ExitCode.USAGE_ERROR
    assert json.loads(bad_threshold.stdout)["error"]["code"] == "MPC_FAIL_ON"
    assert "Traceback" not in bad_rule.output + bad_threshold.output


def test_broken_link_is_input_error_and_suppresses_numeric_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    registry = _prepare_registry(tmp_path)
    repository = YamlClaimRegistryRepository()
    stale_entry = next(
        entry
        for entry in registry.entries
        if isinstance(entry.link, DirectLink) and entry.identity.raw_text == r"80.0\%"
    )
    assert isinstance(stale_entry.link, DirectLink)
    broken = replace(
        stale_entry,
        link=replace(
            stale_entry.link,
            metric=replace(stale_entry.link.metric, source_selector="metrics.missing"),
        ),
    )
    repository.save(
        tmp_path,
        ".metricproof/claims.yml",
        registry.with_entry(broken),
    )
    monkeypatch.chdir(tmp_path)

    exit_code, payload, _ = _json_result("--rule", "STALE_VALUE")

    assert exit_code == ExitCode.INPUT_ERROR
    codes = [item["code"] for item in payload["diagnostics"]]
    assert "LINK_SOURCE_MISSING" in codes
    assert "STALE_VALUE" not in codes
    assert payload["ok"] is False


def test_missing_registry_reports_likely_claims_without_modifying_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_project(tmp_path)
    before = _snapshot_inputs(tmp_path)
    monkeypatch.chdir(tmp_path)

    exit_code, payload, _ = _json_result("--rule", "MISSING_PROVENANCE")

    assert exit_code == ExitCode.SUCCESS
    assert payload["summary"]["registry"] == {"unlinked": 5}
    assert payload["summary"]["diagnostics_by_code"] == {"MISSING_PROVENANCE": 5}
    assert not (tmp_path / ".metricproof" / "claims.yml").exists()
    assert _snapshot_inputs(tmp_path) == before


def test_configuration_policy_parses_tolerances_possible_and_default_fail_on(
    tmp_path: Path,
) -> None:
    _write_project(
        tmp_path,
        policy=(
            "  include_possible_missing_provenance: true\n"
            "  missing_provenance_severity: info\n"
            "  fail_on: warning"
        ),
    )
    path = tmp_path / ".metricproof" / "config.yml"
    text = path.read_text(encoding="utf-8").replace(
        "\npolicy:",
        "\nnumeric_tolerances:\n"
        "  default: {absolute: '0.001', relative: '0.01'}\n"
        "  metrics:\n"
        "    accuracy: {absolute: '0.002', relative: '0'}\n"
        "policy:",
    )
    path.write_text(text, encoding="utf-8")

    configuration = YamlConfigurationRepository().load(tmp_path)

    assert configuration.rule_policy.default_tolerance.absolute.as_tuple().exponent == -3
    assert configuration.rule_policy.default_tolerance.relative.as_tuple().exponent == -2
    assert configuration.rule_policy.tolerance_for("accuracy").absolute.as_tuple().exponent == -3
    assert configuration.rule_policy.include_possible_missing_provenance
    assert configuration.rule_policy.missing_provenance_severity.value == "info"
    assert configuration.rule_policy.fail_on.value == "warning"


@pytest.mark.parametrize(
    "tolerance",
    [
        "{absolute: '-1', relative: '0'}",
        "{absolute: 'NaN', relative: '0'}",
        "{absolute: 'bad', relative: '0'}",
    ],
)
def test_configuration_rejects_invalid_numeric_tolerances(
    tmp_path: Path,
    tolerance: str,
) -> None:
    _write_project(tmp_path)
    path = tmp_path / ".metricproof" / "config.yml"
    path.write_text(
        path.read_text(encoding="utf-8") + f"numeric_tolerances:\n  default: {tolerance}\n",
        encoding="utf-8",
    )

    with pytest.raises(ProjectConfigurationError, match="numeric tolerance"):
        YamlConfigurationRepository().load(tmp_path)
