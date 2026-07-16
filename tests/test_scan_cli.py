"""End-user Stage 4A scan CLI behavior and machine-output tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metricproof.application.errors import ExitCode
from metricproof.cli import main as cli_main

runner = CliRunner()


def _write_project(
    root: Path,
    *,
    paper_text: str = "text 8 \\setcounter{page}{7}",
    extra_config: str = "",
) -> None:
    paper = root / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text(paper_text, encoding="utf-8")
    config = root / ".metricproof" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        'schema_version: "1"\npaper_paths: [paper/main.tex]\n' + extra_config,
        encoding="utf-8",
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_scan_help_and_root_help_are_available() -> None:
    root_help = runner.invoke(cli_main.app, ["--help"])
    scan_help = runner.invoke(cli_main.app, ["scan", "--help"])
    assert root_help.exit_code == ExitCode.SUCCESS
    assert "scan" in root_help.stdout
    assert scan_help.exit_code == ExitCode.SUCCESS
    assert "--json" in scan_help.stdout
    assert "--show-all" in scan_help.stdout
    assert "--show-tables" in scan_help.stdout
    assert "--file" in scan_help.stdout


def test_scan_human_output_hides_low_context_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main.app, ["scan"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "LaTeX raw numeric scan" in result.stdout
    assert "MetricProof raw numeric candidates" in result.stdout
    assert "8" in result.stdout
    assert "7" not in result.stdout
    assert result.stderr == ""


def test_scan_show_all_includes_command_arguments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main.app, ["scan", "--show-all"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "7" in result.stdout
    assert "command_argument" in result.stdout


def test_scan_json_is_clean_parseable_and_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, paper_text="value 87.2\\% and 1.2e-3")
    monkeypatch.chdir(tmp_path)
    first = runner.invoke(cli_main.app, ["scan", "--json"])
    second = runner.invoke(cli_main.app, ["scan", "--json"])
    assert first.exit_code == ExitCode.SUCCESS
    assert first.stdout == second.stdout
    assert first.stderr == ""
    payload = json.loads(first.stdout)
    assert payload["schema_version"] == "2"
    assert payload["result_type"] == "paper_scan"
    assert payload["summary"]["raw_candidate_count"] == 2
    assert payload["candidates"][0]["value"]["canonical"] == "0.872"
    assert payload["candidates"][0]["location"]["char_start"] is not None
    assert payload["summary"]["table_count"] == 0
    assert payload["tables"] == []


def test_scan_file_filters_only_a_configured_graph_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, paper_text="main 1 \\input{section}")
    (tmp_path / "paper" / "section.tex").write_text("section 2", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    selected = runner.invoke(
        cli_main.app,
        ["scan", "--json", "--file", r"paper\section.tex"],
    )
    assert selected.exit_code == ExitCode.SUCCESS
    payload = json.loads(selected.stdout)
    assert [item["raw_text"] for item in payload["candidates"]] == ["2"]
    rejected = runner.invoke(
        cli_main.app,
        ["scan", "--file", "paper/not-in-graph.tex"],
    )
    assert rejected.exit_code == ExitCode.USAGE_ERROR
    assert "MPC_CONFIG" in rejected.stderr


def test_scan_missing_config_and_missing_paper_paths_are_usage_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    missing_config = runner.invoke(cli_main.app, ["scan"])
    assert missing_config.exit_code == ExitCode.USAGE_ERROR
    assert "MPC_CONFIG" in missing_config.stderr
    config = tmp_path / ".metricproof" / "config.yml"
    config.parent.mkdir()
    config.write_text('schema_version: "1"\n', encoding="utf-8")
    missing_papers = runner.invoke(cli_main.app, ["scan", "--json"])
    assert missing_papers.exit_code == ExitCode.USAGE_ERROR
    assert missing_papers.stderr == ""
    assert json.loads(missing_papers.stdout)["error"]["code"] == "MPC_CONFIG"


def test_scan_outputs_recoverable_data_but_uses_input_exit_for_missing_include(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, paper_text="value 1 \\input{missing} after 2")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main.app, ["scan", "--json"])
    assert result.exit_code == ExitCode.INPUT_ERROR
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert [item["raw_text"] for item in payload["candidates"]] == ["1", "2"]
    assert payload["diagnostics"][0]["code"] == "MPE_LATEX_INCLUDE_MISSING"


def test_scan_no_candidates_has_explicit_human_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, paper_text="no numeric content")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main.app, ["scan"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "No raw numeric candidates" in result.stdout


def test_scan_human_mean_std_uses_portable_ascii_separator(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, paper_text=r"value $0.872 \pm 0.004$")
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(cli_main.app, ["scan"])
    assert result.exit_code == ExitCode.SUCCESS
    assert "0.872 +/- 0.004" in result.stdout


def test_scan_does_not_modify_project_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(tmp_path, paper_text="value 1")
    before = _snapshot(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert runner.invoke(cli_main.app, ["scan"]).exit_code == ExitCode.SUCCESS
    assert runner.invoke(cli_main.app, ["scan", "--json"]).exit_code == ExitCode.SUCCESS
    assert _snapshot(tmp_path) == before


def test_scan_maps_interrupt_and_internal_errors_without_traceback_or_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt(selected_file: str | None):
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "_load_paper_scan", interrupt)
    interrupted = runner.invoke(cli_main.app, ["scan"])
    assert interrupted.exit_code == ExitCode.INTERRUPTED
    assert "MP_INTERRUPTED" in interrupted.stderr
    assert "Traceback" not in interrupted.output

    def internal(selected_file: str | None):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(cli_main, "_load_paper_scan", internal)
    failed = runner.invoke(cli_main.app, ["scan", "--json"])
    assert failed.exit_code == ExitCode.INTERNAL_ERROR
    assert failed.stderr == ""
    assert "secret detail" not in failed.stdout
    assert json.loads(failed.stdout)["error"]["code"] == "MP_INTERNAL"


def test_scan_table_summary_show_tables_and_versioned_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(
        tmp_path,
        paper_text=r"""\begin{table}
\caption{Main results}
\label{tab:main}
\begin{tabular}{cc}
\toprule
Model & Score \\
A & baseline 84.1, ours \textbf{87.2} \\
\multicolumn{2}{c}{\underline{Total 90}} \\
\bottomrule
\end{tabular}
\end{table}
""",
    )
    monkeypatch.chdir(tmp_path)

    summary = runner.invoke(cli_main.app, ["scan"])
    assert summary.exit_code == ExitCode.SUCCESS
    assert "1 table(s) (1 parsed, 0 degraded, 0 unsupported)" in summary.stdout
    assert "MetricProof LaTeX tables" not in summary.stdout

    detailed = runner.invoke(cli_main.app, ["scan", "--show-tables"])
    assert detailed.exit_code == ExitCode.SUCCESS
    assert "MetricProof LaTeX tables" in detailed.stdout
    assert "Main results / tab:main" in detailed.stdout
    assert "Table 1 cells: paper/main.tex" in detailed.stdout
    assert "87.2" in detailed.stdout
    assert "bold" in detailed.stdout
    assert "90" in detailed.stdout
    assert "underline" in detailed.stdout

    machine = runner.invoke(cli_main.app, ["scan", "--json"])
    assert machine.exit_code == ExitCode.SUCCESS
    assert machine.stderr == ""
    payload = json.loads(machine.stdout)
    assert payload["schema_version"] == "2"
    assert payload["result_type"] == "paper_scan"
    assert payload["summary"]["table_count"] == 1
    table = payload["tables"][0]
    assert table["caption"]["normalized_text"] == "Main results"
    assert table["label"]["normalized_text"] == "tab:main"
    assert table["column_spec"]["expected_column_count"] == 2
    assert table["location"]["char_start"] is not None
    first_numeric = table["rows"][1]["cells"][1]["numeric_references"]
    assert [item["raw_text"] for item in first_numeric] == ["84.1", "87.2"]
    assert first_numeric[0]["formatting"] == []
    assert first_numeric[1]["formatting"] == ["bold"]


def test_scan_show_tables_reports_degraded_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(
        tmp_path,
        paper_text=(
            r"\begin{tabular}{cc}"
            r"\multirow{2}{*}{Group} & 1 \\"
            r"A & 2 \\"
            r"\end{tabular}"
        ),
    )
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(cli_main.app, ["scan", "--show-tables"])

    assert result.exit_code == ExitCode.SUCCESS
    assert "1 table(s) (0 parsed, 1 degraded, 0 unsupported)" in result.stdout
    assert "MPW_LATEX_MULTIROW_UNSUPPORTED" in result.stdout
    assert "MPW_LATEX_MULTIROW_UNSUPPORTED" in result.stderr


def test_scan_file_filters_tables_as_well_as_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_project(
        tmp_path,
        paper_text=r"main 1 \begin{tabular}{c}10\end{tabular} \input{section}",
    )
    (tmp_path / "paper" / "section.tex").write_text(
        r"section 2 \begin{tabular}{c}20\end{tabular}",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    selected = runner.invoke(
        cli_main.app,
        ["scan", "--json", "--file", r"paper\section.tex"],
    )

    assert selected.exit_code == ExitCode.SUCCESS
    payload = json.loads(selected.stdout)
    assert payload["summary"]["table_count"] == 1
    assert [item["location"]["path"] for item in payload["tables"]] == ["paper/section.tex"]
