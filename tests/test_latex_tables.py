"""Stage 4B1 bounded LaTeX table structure tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from metricproof.adapters import latex_tables
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.domain.paper import (
    LatexFormattingKind,
    LatexTableKind,
    LatexTableReliability,
    LatexTableStructureKind,
)


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def _scan(root: Path, entries: tuple[str, ...] = ("main.tex",)):
    return LocalLatexPaperScanner().scan(root, entries, ())


def test_table_container_metadata_crlf_include_and_stable_ranges(tmp_path: Path) -> None:
    _write(tmp_path, "main.tex", "\\input{sections/results}\r\n")
    source = (
        "\\begin{table*}\r\n"
        "\\label{tab:before}\r\n"
        "\\begin{tabular}{lr}\r\n"
        "A & 1 \\\\\r\n"
        "\\end{tabular}\r\n"
        "\\caption[Short]{Main {results}}\r\n"
        "\\end{table*}\r\n"
        "\\begin{tabular}{c}standalone 2\\end{tabular}\r\n"
    )
    _write(tmp_path, "sections/results.tex", source)

    result = _scan(tmp_path)

    assert result.complete
    assert result.statistics.table_count == 2
    assert result.statistics.parsed_table_count == 2
    contained, standalone = result.tables
    assert contained.environment is LatexTableKind.TABULAR
    assert contained.container_environment is LatexTableKind.TABLE_STAR
    assert contained.caption is not None
    assert contained.caption.raw_text == "Main {results}"
    assert contained.caption.normalized_text == "Main results"
    assert contained.label is not None
    assert contained.label.normalized_text == "tab:before"
    assert contained.location.path == "sections/results.tex"
    assert source[contained.location.char_start : contained.location.char_end].startswith(
        "\\begin{tabular}"
    )
    assert contained.location.line == 3
    assert standalone.container_environment is None
    assert standalone.caption is None
    assert standalone.rows[0].cells[0].normalized_text == "standalone 2"


def test_rows_respect_escaped_group_math_nested_environment_and_masking(tmp_path: Path) -> None:
    source = (
        "\\begin{tabular}{lll}\n"
        "A \\& B & {C & D} & $x & y$ \\\\\n"
        "left & \\begin{minipage}{1cm}nested & value\\end{minipage} & right \\\\\n"
        "% fake & cell \\\\\n"
        "7 & 8 & 9 \\\\\n"
        "\\begin{verbatim}fake & 10 \\\\ \\end{tabular}\\end{verbatim}\n"
        "11 & 12 & 13 \\\\\n"
        "\\end{tabular}\n"
    )
    _write(tmp_path, "main.tex", source)

    result = _scan(tmp_path)

    assert result.complete
    table = result.tables[0]
    assert [row.logical_column_count for row in table.rows] == [3, 3, 3, 3]
    assert [cell.normalized_text for cell in table.rows[0].cells] == [
        "A & B",
        "C & D",
        "$x & y$",
    ]
    assert "nested & value" in table.rows[1].cells[1].normalized_text
    assert [cell.normalized_text for cell in table.rows[2].cells] == ["7", "8", "9"]
    assert [cell.normalized_text for cell in table.rows[3].cells] == ["11", "12", "13"]
    assert [item.raw_text for item in result.candidates if item.location.path == "main.tex"] == [
        "7",
        "8",
        "9",
        "11",
        "12",
        "13",
    ]


def test_column_specs_tabular_star_structure_and_empty_last_cell(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{tabular*}{\\textwidth}[t]{|p{2cm}*{2}{c}@{}r|}\n"
        "\\toprule A & B & C & \\\\\n"
        "\\cline{1-2} D & E & F & G \\tabularnewline[2pt]\n"
        "\\cmidrule(lr){2-3}\\addlinespace\\bottomrule\n"
        "\\end{tabular*}\n",
    )

    result = _scan(tmp_path)

    assert result.complete
    table = result.tables[0]
    assert table.environment is LatexTableKind.TABULAR_STAR
    assert table.column_spec is not None
    assert table.column_spec.expected_column_count == 4
    assert table.column_spec.raw_latex == "{|p{2cm}*{2}{c}@{}r|}"
    assert table.rows[0].cells[-1].is_empty
    assert [item.kind for item in table.rows[0].structure_markers] == [
        LatexTableStructureKind.TOPRULE
    ]
    assert [item.kind for item in table.rows[1].structure_markers] == [
        LatexTableStructureKind.CLINE
    ]
    assert [item.kind for item in table.structure_markers] == [
        LatexTableStructureKind.CMIDRULE,
        LatexTableStructureKind.ADDLINESPACE,
        LatexTableStructureKind.BOTTOMRULE,
    ]


def test_multicolumn_multirow_numeric_identity_and_exact_formatting(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{tabular}{ccc}\n"
        "\\multicolumn{2}{c}{Total \\textbf{20.5\\%}} & \\underline{3} \\\\\n"
        "\\multirow{2}{*}{Group 4} & 5 & 6 \\\\\n"
        "A & 7 & 8 \\\\\n"
        "\\end{tabular}\n",
    )

    result = _scan(tmp_path)

    table = result.tables[0]
    first = table.rows[0]
    assert first.logical_column_count == 3
    assert first.cells[0].logical_column_span == 2
    assert first.cells[0].logical_column_start == 0
    assert first.cells[0].multicolumn_format == "c"
    bold_reference = first.cells[0].numeric_references[0]
    assert bold_reference.candidate is next(
        item for item in result.candidates if item.raw_text == "20.5\\%"
    )
    assert bold_reference.formatting == (LatexFormattingKind.BOLD,)
    assert first.cells[1].numeric_references[0].formatting == (LatexFormattingKind.UNDERLINE,)
    assert table.reliability is LatexTableReliability.DEGRADED
    assert table.rows[1].cells[0].limitations == ("MPW_LATEX_MULTIROW_UNSUPPORTED",)
    assert "MPW_LATEX_MULTIROW_UNSUPPORTED" in {item.code for item in table.diagnostics}
    formatting = first.cells[0].formatting[0]
    source = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert source[
        formatting.content_location.char_start : formatting.content_location.char_end
    ] == ("20.5\\%")


@pytest.mark.parametrize("environment", ["longtable", "tabularx", "array", "matrix", "aligned"])
def test_recognized_unsupported_table_environments_are_explicit(
    tmp_path: Path, environment: str
) -> None:
    argument = "{2cm}{cc}" if environment == "tabularx" else "{cc}"
    _write(
        tmp_path,
        "main.tex",
        f"\\begin{{{environment}}}{argument} A & 1 \\\\ \\end{{{environment}}}",
    )

    result = _scan(tmp_path)

    assert not result.complete
    assert result.statistics.unsupported_table_count == 1
    assert result.tables[0].reliability is LatexTableReliability.UNSUPPORTED
    assert result.tables[0].rows == ()
    assert {item.code for item in result.tables[0].diagnostics} == {
        "MPW_LATEX_UNSUPPORTED_TABLE_ENVIRONMENT"
    }


def test_invalid_multicolumn_unclosed_context_and_column_mismatch_degrade(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{tabular}{cc}\n"
        "\\multicolumn{x}{c}{bad} & 1 & 2 \\\\\n"
        "A & {open 2 \\\\\n"
        "\\end{tabular}\n",
    )

    result = _scan(tmp_path)

    assert not result.complete
    table = result.tables[0]
    assert table.reliability is LatexTableReliability.DEGRADED
    codes = {item.code for item in table.diagnostics}
    assert "MPW_LATEX_MULTICOLUMN_SPAN_INVALID" in codes
    assert "MPW_LATEX_UNCLOSED_CELL_CONTEXT" in codes
    assert "MPW_LATEX_COLUMN_COUNT_MISMATCH" in codes


def test_resource_limits_stop_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(latex_tables, "MAX_LATEX_TABLE_ROWS", 1)
    monkeypatch.setattr(latex_tables, "MAX_LATEX_MULTICOLUMN_SPAN", 2)
    _write(
        tmp_path,
        "main.tex",
        "\\begin{tabular}{ccc}"
        "\\multicolumn{3}{c}{too wide} \\\\ "
        "A & B & C \\\\ "
        "D & E & F \\\\"
        "\\end{tabular}",
    )

    result = _scan(tmp_path)

    assert not result.complete
    assert result.tables[0].reliability is LatexTableReliability.DEGRADED
    assert {item.code for item in result.diagnostics} >= {
        "MPE_LATEX_MULTICOLUMN_SPAN_LIMIT",
        "MPE_LATEX_TABLE_ROW_LIMIT",
    }


def test_nested_tabular_is_retained_with_limitation(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{tabular}{cc}outer & \\begin{tabular}{c}inner 1\\end{tabular} \\\\\\end{tabular}",
    )

    result = _scan(tmp_path)

    assert not result.complete
    assert len(result.tables) == 2
    assert "MPW_LATEX_NESTED_TABULAR" in {item.code for item in result.diagnostics}
    assert all(item.reliability is LatexTableReliability.DEGRADED for item in result.tables)


def test_one_container_can_share_metadata_with_multiple_tabulars(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{table}\n"
        "\\caption{Run 2026 results}\\label{tab:shared}\n"
        "\\begin{tabular}{c}first 1\\end{tabular}\n"
        "\\begin{tabular}{c}second 2\\end{tabular}\n"
        "\\end{table}\n",
    )

    result = _scan(tmp_path)

    assert result.complete
    assert len(result.tables) == 2
    assert all(table.caption is not None for table in result.tables)
    assert all(table.label is not None for table in result.tables)
    assert {table.caption.normalized_text for table in result.tables if table.caption} == {
        "Run 2026 results"
    }
    assert [
        reference.candidate.raw_text
        for table in result.tables
        for row in table.rows
        for cell in row.cells
        for reference in cell.numeric_references
    ] == ["1", "2"]
    assert "2026" in [candidate.raw_text for candidate in result.candidates]


def test_duplicate_caption_and_label_are_locatable_limitations(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{table}"
        "\\caption{first}\\caption{second}"
        "\\label{one}\\label{two}"
        "\\begin{tabular}{c}1\\end{tabular}"
        "\\end{table}",
    )

    result = _scan(tmp_path)

    assert not result.complete
    codes = {item.code for item in result.tables[0].diagnostics}
    assert codes == {"MPW_LATEX_DUPLICATE_CAPTION", "MPW_LATEX_DUPLICATE_LABEL"}
    assert all(item.location.line == 1 for item in result.tables[0].diagnostics)


@pytest.mark.parametrize(
    ("specification", "expected"),
    [
        ("lcr", 3),
        ("|l|c|r|", 3),
        ("@{}lcc@{}", 3),
        ("p{1cm}m{2cm}b{3cm}", 3),
        ("*{2}{lr}", 4),
    ],
)
def test_supported_column_specifications_are_counted(
    tmp_path: Path, specification: str, expected: int
) -> None:
    row = " & ".join(f"cell{index}" for index in range(expected))
    _write(
        tmp_path,
        "main.tex",
        f"\\begin{{tabular}}{{{specification}}}{row}\\end{{tabular}}",
    )

    result = _scan(tmp_path)

    assert result.complete
    assert result.tables[0].expected_column_count == expected


def test_custom_column_spec_is_preserved_without_guessing(tmp_path: Path) -> None:
    _write(tmp_path, "main.tex", "\\begin{tabular}{Xc}A & 1\\end{tabular}")

    result = _scan(tmp_path)

    table = result.tables[0]
    assert not result.complete
    assert table.column_spec is not None
    assert table.column_spec.raw_latex == "{Xc}"
    assert table.expected_column_count is None
    assert {item.code for item in table.diagnostics} == {"MPW_LATEX_COLUMN_SPEC_UNAVAILABLE"}


def test_nested_formatting_is_candidate_specific_and_unsupported_forms_are_not_mapped(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{tabular}{c}"
        "Baseline 84.1; ours \\textbf{\\underline{87.2}}; "
        "math $\\textbf{1.0}$; unsupported \\mathbf{88.0}; textbf word 89.0"
        "\\end{tabular}",
    )

    result = _scan(tmp_path)

    cell = result.tables[0].rows[0].cells[0]
    formatting_by_raw = {
        reference.candidate.raw_text: reference.formatting for reference in cell.numeric_references
    }
    assert formatting_by_raw == {
        "84.1": (),
        "87.2": (LatexFormattingKind.BOLD, LatexFormattingKind.UNDERLINE),
        "1.0": (LatexFormattingKind.BOLD,),
        "88.0": (),
        "89.0": (),
    }
    assert [item.kind for item in cell.formatting] == [
        LatexFormattingKind.BOLD,
        LatexFormattingKind.UNDERLINE,
        LatexFormattingKind.BOLD,
    ]


def test_invalid_structure_command_recovers_the_following_row(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "main.tex",
        "\\begin{tabular}{cc}\\cline A & 1 \\\\ B & 2\\end{tabular}",
    )

    result = _scan(tmp_path)

    table = result.tables[0]
    assert not result.complete
    assert len(table.rows) == 2
    assert [cell.normalized_text for cell in table.rows[0].cells] == ["A", "1"]
    assert "MPW_LATEX_STRUCTURE_COMMAND_INVALID" in {item.code for item in table.diagnostics}


def test_unexpected_end_and_unclosed_table_are_diagnostic_without_losing_other_files(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "main.tex", "\\input{bad}\\input{good}\\end{tabular} outside 9")
    _write(tmp_path, "bad.tex", "\\begin{tabular}{c}bad 1")
    _write(tmp_path, "good.tex", "\\begin{tabular}{c}good 2\\end{tabular}")

    result = _scan(tmp_path)

    codes = {item.code for item in result.diagnostics}
    assert "MPW_LATEX_UNEXPECTED_TABLE_END" in codes
    assert "MPW_LATEX_UNCLOSED_TABLE_ENVIRONMENT" in codes
    assert [candidate.raw_text for candidate in result.candidates] == ["1", "2", "9"]
    assert len(result.tables) == 2
    assert any(table.reliability is LatexTableReliability.PARSED for table in result.tables)
    assert any(table.reliability is LatexTableReliability.DEGRADED for table in result.tables)


def test_table_count_and_cell_length_limits_preserve_other_candidates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(latex_tables, "MAX_LATEX_TABLES", 1)
    monkeypatch.setattr(latex_tables, "MAX_LATEX_CELL_CHARS", 4)
    _write(
        tmp_path,
        "main.tex",
        "outside 7 "
        "\\begin{tabular}{c}cell-too-long 1\\end{tabular} "
        "\\begin{tabular}{c}second 2\\end{tabular}",
    )

    result = _scan(tmp_path)

    assert not result.complete
    assert len(result.tables) == 1
    assert [candidate.raw_text for candidate in result.candidates] == ["7", "1", "2"]
    assert {item.code for item in result.diagnostics} >= {
        "MPE_LATEX_TABLE_LIMIT",
        "MPE_LATEX_CELL_TOO_LONG",
    }


@pytest.mark.parametrize(
    ("limit_name", "limit_value", "source", "expected_code"),
    [
        (
            "MAX_LATEX_ROW_CELLS",
            2,
            "\\begin{tabular}{ccc}A & B & C\\end{tabular}",
            "MPE_LATEX_ROW_CELL_LIMIT",
        ),
        (
            "MAX_LATEX_TABLE_CELLS",
            2,
            "\\begin{tabular}{cc}A & B \\\\ C & D\\end{tabular}",
            "MPE_LATEX_TABLE_CELL_LIMIT",
        ),
    ],
)
def test_cell_count_limits_stop_the_affected_table(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit_name: str,
    limit_value: int,
    source: str,
    expected_code: str,
) -> None:
    monkeypatch.setattr(latex_tables, limit_name, limit_value)
    _write(tmp_path, "main.tex", source)

    result = _scan(tmp_path)

    assert not result.complete
    assert expected_code in {item.code for item in result.diagnostics}
