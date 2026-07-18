"""High-value Stage 6 rule, safe-config, report, and showcase tests."""

from __future__ import annotations

import json
import shutil
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from metricproof.adapters import experiment_configs as experiment_configs_module
from metricproof.adapters.experiment_configs import LocalExperimentConfigReader
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.adapters.reports import render_html_report, render_json_report, write_report
from metricproof.application.errors import ExitCode
from metricproof.cli.main import app
from metricproof.domain.diagnostics import (
    CHECK_RESULT_SCHEMA_VERSION,
    CheckDiagnosticKind,
    CheckResult,
    CheckSummary,
    RuleExecutionSummary,
    make_check_diagnostic,
    make_check_evidence,
)
from metricproof.domain.links import NumericTolerance
from metricproof.domain.models import ExperimentRun, Severity, SourceLocation
from metricproof.domain.paper import LatexFormattingKind, LatexTableText
from metricproof.domain.stage6 import (
    ComparisonSpec,
    ConfigValue,
    ConfigValueKind,
    ExperimentConfigSnapshot,
    MetricDirection,
    TableCheckSpec,
    TableMetricSpec,
    check_unfair_comparison,
    check_wrong_best_mark,
    table_reference,
)


def _scan_table(tmp_path: Path, rows: str):
    rows = rows.rstrip()
    if not rows.endswith("\\\\"):
        rows = rows.rstrip("\\").rstrip() + r" \\"
    (tmp_path / "paper.tex").write_text(
        "\\begin{table}\n"
        "\\caption{Results}\n"
        "\\label{tab:results}\n"
        "\\begin{tabular}{lrr}\n"
        "Method & Accuracy & Error rate \\\\\n"
        f"{rows}\n"
        "\\end{tabular}\n"
        "\\end{table}\n",
        encoding="utf-8",
    )
    scan = LocalLatexPaperScanner().scan(tmp_path, ("paper.tex",))
    assert len(scan.tables) == 1
    return scan.tables[0]


def _table_spec(
    *,
    tolerance: str = "0",
    second: LatexFormattingKind | None = LatexFormattingKind.UNDERLINE,
) -> TableCheckSpec:
    return TableCheckSpec(
        table="tab:results",
        header_row=0,
        data_start_row=1,
        label_column=0,
        metric_columns=(
            TableMetricSpec(1, "accuracy", MetricDirection.HIGHER),
            TableMetricSpec(2, "error_rate", MetricDirection.LOWER),
        ),
        second_best_format=second,
        tie_tolerance=Decimal(tolerance),
    )


def test_best_mark_higher_lower_and_quiet_cells(tmp_path: Path) -> None:
    table = _scan_table(
        tmp_path,
        "A & 70.0 & 30.0 \\\\\n"
        "B & \\textbf{90.0} & \\textbf{10.0} \\\\\n"
        "C & \\underline{80.0} & \\underline{20.0} \\",
    )
    assert check_wrong_best_mark((table,), (_table_spec(),)) == ()


def test_best_mark_reports_wrong_bold_and_missing_second(tmp_path: Path) -> None:
    table = _scan_table(
        tmp_path,
        "A & 70.0 & 30.0 \\\\\n"
        "B & \\textbf{90.0} & \\textbf{10.0} \\\\\n"
        "C & \\textbf{80.0} & \\underline{20.0} \\",
    )
    diagnostics = check_wrong_best_mark((table,), (_table_spec(),))
    assert len(diagnostics) == 2
    assert {item.expected for item in diagnostics} == {
        "best uses bold",
        "second-best uses underline",
    }
    assert all(item.subject_id == "table:tab:results" for item in diagnostics)


def test_best_mark_supports_ties_and_decimal_tolerance(tmp_path: Path) -> None:
    table = _scan_table(
        tmp_path,
        "A & \\textbf{90.0} & 30.0 \\\\\n"
        "B & \\textbf{89.9999} & \\textbf{10.0} \\\\\n"
        "C & \\underline{80.0} & \\underline{20.0} \\",
    )
    assert check_wrong_best_mark((table,), (_table_spec(tolerance="0.001"),)) == ()


def test_best_mark_can_disable_second_best_policy(tmp_path: Path) -> None:
    table = _scan_table(
        tmp_path,
        "A & 70.0 & 30.0 \\\\\nB & \\textbf{90.0} & \\textbf{10.0} \\\\\nC & 80.0 & 20.0 \\",
    )
    assert check_wrong_best_mark((table,), (_table_spec(second=None),)) == ()


@pytest.mark.parametrize(
    "rows, reason",
    [
        ("A & 70.0 & 30.0 \\\\\nB & \\custombest{90.0} & 10.0 \\", "unsupported"),
        ("\\multirow{2}{*}{A} & 70.0 & 30.0 \\\\\nB & 90.0 & 10.0 \\", "degraded"),
        ("A & 70.0 & 30.0 \\\\\nB & 90.0 & 10.0 & 5.0 \\", "degraded"),
    ],
)
def test_best_mark_degrades_instead_of_guessing(tmp_path: Path, rows: str, reason: str) -> None:
    table = _scan_table(tmp_path, rows)
    diagnostics = check_wrong_best_mark((table,), (_table_spec(),))
    assert diagnostics
    assert diagnostics[0].kind is CheckDiagnosticKind.LIMITATION
    assert reason in str(diagnostics[0].observed)


def test_best_mark_missing_table_and_out_of_bounds_are_limitations(tmp_path: Path) -> None:
    table = _scan_table(tmp_path, "A & 70.0 & 30.0 \\")
    missing = TableCheckSpec(
        table="missing",
        header_row=0,
        data_start_row=1,
        label_column=0,
        metric_columns=(TableMetricSpec(1, "accuracy", MetricDirection.HIGHER),),
    )
    bounds = TableCheckSpec(
        table="tab:results",
        header_row=0,
        data_start_row=1,
        label_column=0,
        metric_columns=(TableMetricSpec(9, "accuracy", MetricDirection.HIGHER),),
    )
    assert check_wrong_best_mark((table,), (missing,))[0].kind is CheckDiagnosticKind.LIMITATION
    assert "out of bounds" in str(check_wrong_best_mark((table,), (bounds,))[0].observed)


def test_best_mark_supports_mean_std_missing_cells_and_multicolumn(tmp_path: Path) -> None:
    table = _scan_table(
        tmp_path,
        "\\multicolumn{1}{l}{A} & 70.0 \\pm 0.2 & -- \\\\\n"
        "B & \\textbf{90.0 \\pm 0.1} & \\textbf{10.0} \\\\\n"
        "C & \\underline{80.0 \\pm 0.3} & \\underline{20.0} \\",
    )
    assert check_wrong_best_mark((table,), (_table_spec(),)) == ()


def test_stage6_rules_scale_to_many_reviewable_facts(tmp_path: Path) -> None:
    base = _scan_table(
        tmp_path,
        "A & \\textbf{70.0} & \\textbf{30.0} \\\\\nB & 90.0 & 10.0 \\\\\nC & 80.0 & 20.0 \\",
    )
    assert base.label is not None
    tables = tuple(
        replace(
            base,
            label=LatexTableText(f"tab:{index}", f"tab:{index}", base.label.location),
        )
        for index in range(50)
    )
    specs = tuple(replace(_table_spec(), table=f"tab:{index}") for index in range(50))
    comparisons = tuple(
        ComparisonSpec(f"cmp-{index:02}", f"base-{index:02}", f"candidate-{index:02}", ("x",))
        for index in range(50)
    )
    snapshots = tuple(
        snapshot
        for index in range(50)
        for snapshot in (
            ExperimentConfigSnapshot(
                f"base-{index:02}", f"base-{index:02}.yml", (("x", _value("a")),)
            ),
            ExperimentConfigSnapshot(
                f"candidate-{index:02}",
                f"candidate-{index:02}.yml",
                (("x", _value("b")),),
            ),
        )
    )
    started = perf_counter()
    table_diagnostics = check_wrong_best_mark(tables, specs)
    comparison_diagnostics = check_unfair_comparison(comparisons, snapshots)
    elapsed = perf_counter() - started
    assert len(table_diagnostics) == 300
    assert len(comparison_diagnostics) == 50
    assert elapsed < 2


def _value(value: object) -> ConfigValue:
    if value is None:
        return ConfigValue(ConfigValueKind.NULL)
    if isinstance(value, bool):
        return ConfigValue(ConfigValueKind.BOOLEAN, scalar=value)
    if isinstance(value, Decimal):
        return ConfigValue(ConfigValueKind.NUMBER, scalar=value)
    if isinstance(value, str):
        return ConfigValue(ConfigValueKind.STRING, scalar=value)
    if isinstance(value, tuple):
        items = cast(tuple[object, ...], value)
        return ConfigValue(ConfigValueKind.LIST, items=tuple(_value(item) for item in items))
    raise AssertionError(value)


def _comparison(
    left: ConfigValue | None,
    right: ConfigValue | None,
    *,
    tolerance: NumericTolerance | None = None,
    allowed: bool = False,
):
    spec = ComparisonSpec(
        "base-vs-candidate",
        "base",
        "candidate",
        ("training.value",),
        allowed_differences=(("training.value", "Intentional difference."),) if allowed else (),
        tolerances=(("training.value", tolerance or NumericTolerance()),),
    )
    snapshots = (
        ExperimentConfigSnapshot("base", "base.yml", (("training.value", left),)),
        ExperimentConfigSnapshot("candidate", "candidate.yml", (("training.value", right),)),
    )
    return check_unfair_comparison((spec,), snapshots)


@pytest.mark.parametrize(
    "left,right,expected",
    [
        (_value("same"), _value("same"), 0),
        (_value("A"), _value("a"), 1),
        (_value(Decimal("100")), _value("100"), 1),
        (_value(("a", "b")), _value(("a", "b")), 0),
        (_value(("a", "b")), _value(("b", "a")), 1),
        (_value(None), _value(None), 0),
        (None, _value("present"), 1),
    ],
)
def test_declared_comparison_uses_strict_value_semantics(
    left: ConfigValue | None,
    right: ConfigValue | None,
    expected: int,
) -> None:
    assert len(_comparison(left, right)) == expected


def test_declared_comparison_mapping_values_are_deterministic() -> None:
    left = ConfigValue(
        ConfigValueKind.MAPPING,
        entries=(("a", _value(Decimal("1"))), ("b", _value("two"))),
    )
    same = ConfigValue(
        ConfigValueKind.MAPPING,
        entries=(("a", _value(Decimal("1"))), ("b", _value("two"))),
    )
    changed = ConfigValue(
        ConfigValueKind.MAPPING,
        entries=(("a", _value(Decimal("2"))), ("b", _value("two"))),
    )
    assert _comparison(left, same) == ()
    assert len(_comparison(left, changed)) == 1


def test_declared_comparison_relative_tolerance() -> None:
    tolerance = NumericTolerance(absolute=Decimal("0"), relative=Decimal("0.01"))
    assert _comparison(_value(Decimal("100")), _value(Decimal("100.5")), tolerance=tolerance) == ()
    assert (
        len(_comparison(_value(Decimal("100")), _value(Decimal("102")), tolerance=tolerance)) == 1
    )


def test_declared_comparison_numeric_tolerance_and_allowed_difference() -> None:
    tolerance = NumericTolerance(absolute=Decimal("0.01"), relative=Decimal("0"))
    assert _comparison(_value(Decimal("1")), _value(Decimal("1.005")), tolerance=tolerance) == ()
    assert _comparison(_value("base"), _value("candidate"), allowed=True) == ()


def test_declared_comparison_reports_missing_runs_and_both_missing_keys() -> None:
    spec = ComparisonSpec("comparison", "base", "candidate", ("missing",))
    missing_run = check_unfair_comparison((spec,), ())
    assert missing_run[0].kind is CheckDiagnosticKind.INPUT
    snapshots = (
        ExperimentConfigSnapshot("base", "base.yml", (("missing", None),)),
        ExperimentConfigSnapshot("candidate", "candidate.yml", (("missing", None),)),
    )
    missing_key = check_unfair_comparison((spec,), snapshots)
    assert missing_key[0].kind is CheckDiagnosticKind.INPUT
    assert "missing from both" in missing_key[0].message


def _run(reference: str) -> ExperimentRun:
    return ExperimentRun("run", (), (), (), config_reference=reference)


def test_experiment_config_reader_is_safe_exact_and_bounded(tmp_path: Path) -> None:
    (tmp_path / "run.json").write_text(
        '{"training":{"epochs":100,"layers":[1,2]},"flag":true}', encoding="utf-8"
    )
    result = LocalExperimentConfigReader().read(
        tmp_path,
        _run("run.json"),
        ("flag", "training.epochs", "training.layers"),
    )
    assert not result.diagnostics
    snapshot = result.snapshots[0]
    assert snapshot.value_for("training.epochs") == _value(Decimal("100"))
    assert snapshot.value_for("training.layers") == _value((Decimal("1"), Decimal("2")))


@pytest.mark.parametrize(
    "name,text",
    [
        ("duplicate.json", '{"x":1,"x":2}'),
        ("unsafe.yml", "x: !!python/object/apply:os.system ['echo unsafe']"),
        ("multi.yml", "x: 1\n---\nx: 2\n"),
        ("nonfinite.json", '{"x":NaN}'),
    ],
)
def test_experiment_config_reader_rejects_unsafe_or_ambiguous_input(
    tmp_path: Path, name: str, text: str
) -> None:
    (tmp_path / name).write_text(text, encoding="utf-8")
    result = LocalExperimentConfigReader().read(tmp_path, _run(name), ("x",))
    assert not result.snapshots
    assert result.diagnostics[0].severity is Severity.ERROR


def _report_result(*, malicious: bool = False) -> CheckResult:
    location = SourceLocation("paper/<script>.tex" if malicious else "paper/main.tex", line=3)
    diagnostic = make_check_diagnostic(
        kind=CheckDiagnosticKind.RULE,
        code="STALE_VALUE",
        severity=Severity.ERROR,
        message="</script><script>alert(1)</script>" if malicious else "Value differs.",
        location=location,
        evidence=(
            make_check_evidence(
                kind="claim",
                summary='caption "<&>' if malicious else "Reviewable evidence.",
                location=location,
            ),
        ),
        confidence=Decimal("1"),
        remediation="Review manually.",
        claim_id="clm_0123456789abcdef0123",
        observed="<bad>" if malicious else "1",
        expected="2",
    )
    rules = tuple(
        RuleExecutionSummary(code, "executed", 0, 0, 1 if code == "STALE_VALUE" else 0, 0)
        for code in sorted(
            {
                "STALE_VALUE",
                "WRONG_DELTA",
                "MISSING_PROVENANCE",
                "WRONG_BEST_MARK",
                "UNFAIR_COMPARISON",
            }
        )
    )
    return CheckResult(
        CHECK_RESULT_SCHEMA_VERSION,
        "0.1.0",
        "showcase",
        CheckSummary(
            1,
            (("active", 1),),
            (),
            (("STALE_VALUE", 1),),
            (("error", 1),),
            scanned_file_count=1,
            rule_summaries=rules,
        ),
        (diagnostic,),
    )


def test_html_report_is_offline_escaped_and_readable_without_javascript() -> None:
    html = render_html_report(_report_result(malicious=True), generated_at=None)
    assert "https://" not in html and "http://" not in html
    assert "<script" not in html
    assert "&lt;script&gt;" in html
    assert "STALE_VALUE" in html and "Observed" in html and "Evidence" in html
    assert "omitted for deterministic output" in html


def test_html_report_handles_a_clear_project() -> None:
    rules = tuple(
        RuleExecutionSummary(code, "executed", 0, 0, 0, 0)
        for code in sorted(
            {
                "STALE_VALUE",
                "WRONG_DELTA",
                "MISSING_PROVENANCE",
                "WRONG_BEST_MARK",
                "UNFAIR_COMPARISON",
            }
        )
    )
    result = CheckResult(
        CHECK_RESULT_SCHEMA_VERSION,
        "0.1.0",
        "clear",
        CheckSummary(0, (), (), (), (), rule_summaries=rules),
        (),
    )
    html = render_html_report(result, generated_at=None)
    assert "CLEAR" in html
    assert "No diagnostics were produced." in html


def test_report_writes_atomically_creates_parent_and_json_is_parseable(tmp_path: Path) -> None:
    result = _report_result()
    html_path = write_report(tmp_path, "reports/report.html", "html", result, no_timestamp=True)
    first = html_path.read_bytes()
    write_report(tmp_path, "reports/report.html", "html", result, no_timestamp=True)
    assert html_path.read_bytes() == first
    assert not tuple(html_path.parent.glob("*.tmp"))
    payload = json.loads(render_json_report(result, generated_at=None))
    assert payload["schema_version"] == CHECK_RESULT_SCHEMA_VERSION
    assert payload["summary"]["rules"][0]["code"] == "MISSING_PROVENANCE"
    with pytest.raises(ValueError, match="project-relative"):
        write_report(tmp_path, "../escape.html", "html", result, no_timestamp=True)


def test_showcase_report_matches_check_and_preserves_all_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = Path(__file__).resolve().parents[1] / "examples" / "mvp-demo"
    project = tmp_path / "showcase"
    shutil.copytree(source, project)
    tracked = tuple(
        sorted(
            path
            for folder in (".metricproof", "paper", "runs", "configs")
            for path in (project / folder).rglob("*")
            if path.is_file()
        )
    )
    before = {path: path.read_bytes() for path in tracked}
    monkeypatch.chdir(project)
    runner = CliRunner()
    checked = runner.invoke(app, ["check", "--json"])
    reported = runner.invoke(
        app,
        ["report", "--format", "html", "--output", "report.html", "--no-timestamp"],
    )
    json_report = runner.invoke(
        app,
        ["report", "--format", "json", "--output", "report.json", "--no-timestamp"],
    )
    assert (
        checked.exit_code
        == reported.exit_code
        == json_report.exit_code
        == ExitCode.ANALYSIS_FAILURE
    )
    check_payload = cast(dict[str, Any], json.loads(checked.stdout))
    report_payload = cast(dict[str, Any], json.loads((project / "report.json").read_text()))
    assert (
        report_payload["summary"]["diagnostic_count"]
        == check_payload["summary"]["diagnostic_count"]
    )
    report_html = (project / "report.html").read_text(encoding="utf-8")
    assert all(code in report_html for code in check_payload["summary"]["diagnostics_by_code"])
    assert "http://" not in report_html and "https://" not in report_html
    assert {path: path.read_bytes() for path in tracked} == before


def test_stage6_domain_models_reject_ambiguous_or_unstable_contracts() -> None:
    with pytest.raises(ValueError):
        TableMetricSpec(-1, "accuracy", MetricDirection.HIGHER)
    with pytest.raises(ValueError):
        TableMetricSpec(1, " ", MetricDirection.HIGHER)
    metric = TableMetricSpec(1, "accuracy", MetricDirection.HIGHER)
    with pytest.raises(ValueError):
        TableCheckSpec(" ", 0, 1, 0, (metric,))
    with pytest.raises(ValueError):
        TableCheckSpec("tab:x", -1, 1, 0, (metric,))
    with pytest.raises(ValueError):
        TableCheckSpec("tab:x", 0, 2, 0, (metric,), data_end_row=1)
    with pytest.raises(ValueError):
        TableCheckSpec("tab:x", 0, 1, 0, (metric,), exclude_rows=(2, 1))
    with pytest.raises(ValueError):
        TableCheckSpec("tab:x", 0, 1, 0, ())
    with pytest.raises(ValueError):
        TableCheckSpec("tab:x", 0, 1, 0, (metric, metric))
    with pytest.raises(ValueError):
        TableCheckSpec("tab:x", 0, 1, 1, (metric,))
    with pytest.raises(ValueError):
        TableCheckSpec("tab:x", 0, 1, 0, (metric,), tie_tolerance=Decimal("Infinity"))


def test_config_value_models_are_typed_sorted_and_displayable() -> None:
    with pytest.raises(ValueError):
        ConfigValue(ConfigValueKind.LIST, scalar="bad")
    with pytest.raises(ValueError):
        ConfigValue(ConfigValueKind.MAPPING, items=(_value("bad"),))
    with pytest.raises(ValueError):
        ConfigValue(
            ConfigValueKind.MAPPING,
            entries=(("b", _value("two")), ("a", _value("one"))),
        )
    with pytest.raises(ValueError):
        ConfigValue(
            ConfigValueKind.MAPPING,
            entries=(("a", _value("one")), ("a", _value("two"))),
        )
    with pytest.raises(ValueError):
        ConfigValue(ConfigValueKind.STRING, items=(_value("bad"),))
    with pytest.raises(ValueError):
        ConfigValue(ConfigValueKind.NULL, scalar="bad")
    with pytest.raises(ValueError):
        ConfigValue(ConfigValueKind.NUMBER, scalar="1")
    mapping = ConfigValue(
        ConfigValueKind.MAPPING,
        entries=(("enabled", _value(True)), ("items", _value(("x", None)))),
    )
    assert mapping.display == "{enabled: true, items: [x, null]}"
    assert _value(False).display == "false"
    assert _value(Decimal("1.25")).display == "1.25"


def test_snapshot_and_comparison_specs_enforce_stable_contracts() -> None:
    with pytest.raises(ValueError):
        ExperimentConfigSnapshot("", "run.yml", ())
    with pytest.raises(ValueError):
        ExperimentConfigSnapshot("run", "", ())
    with pytest.raises(ValueError):
        ExperimentConfigSnapshot("run", "run.yml", (("b", None), ("a", None)))
    snapshot = ExperimentConfigSnapshot("run", "run.yml", (("x", _value("ok")),))
    assert snapshot.value_for("missing") is None
    with pytest.raises(ValueError):
        ComparisonSpec("", "base", "candidate", ("x",))
    with pytest.raises(ValueError):
        ComparisonSpec("cmp", "base", "candidate", ())
    with pytest.raises(ValueError):
        ComparisonSpec("cmp", "base", "candidate", ("b", "a"))
    with pytest.raises(ValueError):
        ComparisonSpec("cmp", "base", "candidate", ("a", "b"), (("b", "reason"), ("a", "reason")))
    with pytest.raises(ValueError):
        ComparisonSpec("cmp", "base", "candidate", ("x",), (("x", " "),))
    with pytest.raises(ValueError):
        ComparisonSpec("cmp", "base", "candidate", ("x",), note=" ")
    spec = ComparisonSpec("cmp", "base", "candidate", ("x",))
    assert spec.tolerance_for("x") == NumericTolerance()


def test_table_reference_has_deterministic_caption_and_location_fallback(tmp_path: Path) -> None:
    table = _scan_table(tmp_path, "A & 1 & 2 \\")
    assert table.caption is not None
    without_label = replace(table, label=None)
    assert table_reference(without_label).startswith("paper.tex#caption:Results")
    without_caption = replace(without_label, caption=None)
    assert table_reference(without_caption).startswith("paper.tex#char:")


def test_config_reader_reports_absent_missing_directory_format_and_utf8(tmp_path: Path) -> None:
    reader = LocalExperimentConfigReader()
    no_reference = reader.read(tmp_path, ExperimentRun("run", (), (), ()), ("x",))
    assert no_reference.snapshots == () and no_reference.diagnostics == ()
    assert (
        reader.read(tmp_path, _run("missing.yml"), ("x",)).diagnostics[0].code
        == "MPE_CONFIG_NOT_FOUND"
    )
    (tmp_path / "folder.yml").mkdir()
    assert (
        reader.read(tmp_path, _run("folder.yml"), ("x",)).diagnostics[0].code
        == "MPE_CONFIG_PATH_ESCAPE"
    )
    (tmp_path / "run.txt").write_text("x=1", encoding="utf-8")
    assert reader.read(tmp_path, _run("run.txt"), ("x",)).diagnostics[0].code == "MPE_CONFIG_FORMAT"
    (tmp_path / "invalid.yml").write_bytes(b"\xff\xfe")
    assert (
        reader.read(tmp_path, _run("invalid.yml"), ("x",)).diagnostics[0].code
        == "MPE_CONFIG_READ_ERROR"
    )


def test_config_reader_enforces_size_depth_key_and_recursion_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = LocalExperimentConfigReader()
    (tmp_path / "large.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(experiment_configs_module, "MAX_FILE_BYTES", 1)
    assert (
        reader.read(tmp_path, _run("large.json"), ()).diagnostics[0].code == "MPE_CONFIG_TOO_LARGE"
    )
    monkeypatch.setattr(experiment_configs_module, "MAX_FILE_BYTES", 5_000_000)
    monkeypatch.setattr(experiment_configs_module, "MAX_NESTING_DEPTH", 1)
    (tmp_path / "deep.yml").write_text("a:\n  b:\n    c: 1\n", encoding="utf-8")
    assert (
        reader.read(tmp_path, _run("deep.yml"), ("a.b.c",)).diagnostics[0].code
        == "MPE_CONFIG_NESTING"
    )
    monkeypatch.setattr(experiment_configs_module, "MAX_NESTING_DEPTH", 64)
    (tmp_path / "key.yml").write_text("1: value\n", encoding="utf-8")
    assert reader.read(tmp_path, _run("key.yml"), ("x",)).diagnostics[0].code == "MPE_CONFIG_KEY"
    (tmp_path / "recursive-map.yml").write_text("x: &x\n  self: *x\n", encoding="utf-8")
    assert (
        reader.read(tmp_path, _run("recursive-map.yml"), ("x",)).diagnostics[0].code
        == "MPE_CONFIG_SYNTAX"
    )
    (tmp_path / "recursive-list.yml").write_text("x: &x [*x]\n", encoding="utf-8")
    assert (
        reader.read(tmp_path, _run("recursive-list.yml"), ("x",)).diagnostics[0].code
        == "MPE_CONFIG_RECURSIVE"
    )


def test_config_reader_selects_typed_mapping_list_and_array_paths(tmp_path: Path) -> None:
    (tmp_path / "typed.yml").write_text(
        "root:\n  values: [null, true, text, 1.5]\n  mapping: {b: 2, a: one}\n",
        encoding="utf-8",
    )
    result = LocalExperimentConfigReader().read(
        tmp_path,
        _run("typed.yml"),
        (
            "root..bad",
            "root.mapping",
            "root.values.0",
            "root.values.0.more",
            "root.values.1",
            "root.values.2",
            "root.values.3",
            "root.values.99",
            "root.values.bad",
        ),
    )
    assert not result.diagnostics
    snapshot = result.snapshots[0]
    assert snapshot.value_for("root.values.0") == _value(None)
    assert snapshot.value_for("root.values.1") == _value(True)
    assert snapshot.value_for("root.values.2") == _value("text")
    assert snapshot.value_for("root.values.3") == _value(Decimal("1.5"))
    mapping = snapshot.value_for("root.mapping")
    assert mapping is not None and mapping.display == "{a: one, b: 2}"
    assert snapshot.value_for("root..bad") is None
    assert snapshot.value_for("root.values.bad") is None
    assert snapshot.value_for("root.values.99") is None
    assert snapshot.value_for("root.values.0.more") is None


def test_rule_execution_summary_tracks_severity_counts_and_validates_status() -> None:
    summary = RuleExecutionSummary("RULE", "executed", 1, 2, 3, 4)
    assert summary.finding_count == 6
    with pytest.raises(ValueError):
        RuleExecutionSummary("", "executed", 0, 0, 0, 0)
    with pytest.raises(ValueError):
        RuleExecutionSummary("RULE", "unknown", 0, 0, 0, 0)
    with pytest.raises(ValueError):
        RuleExecutionSummary("RULE", "executed", -1, 0, 0, 0)
    with pytest.raises(ValueError):
        RuleExecutionSummary("RULE", "skipped", 0, 0, 0, 0)
