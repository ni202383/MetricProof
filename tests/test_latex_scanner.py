"""Controlled LaTeX graph, masking, numeric, context, and location tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from metricproof.adapters import latex as latex_module
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.domain.models import NumericKind, NumericUnit
from metricproof.domain.paper import LatexSyntacticContext, NumericCandidateKind


def _write(root: Path, relative: str, text: str, *, bom: bool = False) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = text.encode("utf-8")
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + encoded)
    return path


def _scan(
    root: Path,
    entries: tuple[str, ...] = ("paper/main.tex",),
    excludes: tuple[str, ...] = (),
):
    return LocalLatexPaperScanner().scan(root, entries, excludes)


def test_graph_resolves_input_include_relative_paths_and_deduplicates(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        "\\input{sections/results}\n\\include{appendix.tex}\n\\input{sections/results}\n1",
    )
    _write(tmp_path, "paper/sections/results.tex", "\\input{nested/detail}\n2")
    _write(tmp_path, "paper/sections/nested/detail.tex", "3")
    _write(tmp_path, "paper/appendix.tex", "4")

    result = _scan(tmp_path)

    assert result.complete
    assert [item.path for item in result.graph.documents] == [
        "paper/appendix.tex",
        "paper/main.tex",
        "paper/sections/nested/detail.tex",
        "paper/sections/results.tex",
    ]
    assert len(result.graph.edges) == 4
    assert [item.raw_text for item in result.candidates] == ["4", "1", "3", "2"]
    result_candidate = next(
        item for item in result.candidates if item.location.path.endswith("results.tex")
    )
    assert result_candidate.include_chain == (
        "paper/main.tex",
        "paper/sections/results.tex",
    )


def test_multiple_entries_share_one_physical_document_and_provenance(tmp_path: Path) -> None:
    _write(tmp_path, "paper/a.tex", "\\input{shared}")
    _write(tmp_path, "paper/b.tex", "\\input{shared}")
    _write(tmp_path, "paper/shared.tex", "value 9")

    result = _scan(tmp_path, ("paper/b.tex", "paper/a.tex"))

    assert result.graph.entry_paths == ("paper/a.tex", "paper/b.tex")
    assert len([item for item in result.graph.documents if item.path == "paper/shared.tex"]) == 1
    candidate = result.candidates[0]
    assert candidate.entry_paths == ("paper/a.tex", "paper/b.tex")
    assert candidate.include_chain == ("paper/a.tex", "paper/shared.tex")


def test_comments_respect_escaped_percent_and_backslash_parity(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        "visible 1 % hidden 2\n"
        "escaped 3\\% visible 4\n"
        "double \\\\% hidden 5\n"
        "triple \\\\\\% visible 6\n"
        "% \\input{hidden} 7\n",
    )

    result = _scan(tmp_path)

    assert [item.raw_text for item in result.candidates] == ["1", "3\\%", "4", "6"]
    assert result.graph.documents == (result.graph.documents[0],)
    assert not result.graph.edges


@pytest.mark.parametrize("environment", ["verbatim", "Verbatim", "lstlisting", "minted"])
def test_code_environments_hide_numbers_and_includes(tmp_path: Path, environment: str) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        f"before 1\n\\begin{{{environment}}}\n99 \\input{{hidden}}\n"
        f"\\end{{{environment}}}\nafter 2",
    )

    result = _scan(tmp_path)

    assert [item.raw_text for item in result.candidates] == ["1", "2"]
    assert not result.graph.edges


def test_verb_hides_numbers_and_include_like_text(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        "before 1 \\verb|99 \\input{hidden}| after 2 \\verb+88+ end 3",
    )
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["1", "2", "3"]
    assert not result.graph.edges


def test_unclosed_code_environment_is_locatable_and_recovers_other_files(tmp_path: Path) -> None:
    _write(tmp_path, "paper/main.tex", "\\input{good}\n\\begin{verbatim}\n99")
    _write(tmp_path, "paper/good.tex", "value 7")
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["7"]
    diagnostic = next(
        item for item in result.diagnostics if item.code == "MPW_LATEX_UNCLOSED_ENVIRONMENT"
    )
    assert diagnostic.location.path == "paper/main.tex"
    assert diagnostic.location.line == 2
    assert diagnostic.kind.value == "limitation"
    assert not result.complete


def test_numeric_forms_are_exact_and_mean_std_is_composite(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        "12 3.40 .872 -4 +5 1.2e-3 87.2% 91.0\\% 2.0 ± 0.3 and 4.0 \\pm 0.2",
    )
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == [
        "12",
        "3.40",
        ".872",
        "-4",
        "+5",
        "1.2e-3",
        "87.2%",
        "91.0\\%",
        "2.0 ± 0.3",
        "4.0 \\pm 0.2",
    ]
    scientific = result.candidates[5]
    assert scientific.value.kind is NumericKind.SCIENTIFIC
    assert str(scientific.value.parsed) == "0.0012"
    percentage = result.candidates[6]
    assert percentage.value.unit is NumericUnit.RATIO
    assert str(percentage.value.canonical) == "0.872"
    composite = result.candidates[8]
    assert composite.kind is NumericCandidateKind.MEAN_STD
    assert composite.uncertainty is not None
    assert str(composite.uncertainty.parsed) == "0.3"


def test_sentence_punctuation_is_not_part_of_an_integer_candidate(tmp_path: Path) -> None:
    _write(tmp_path, "paper/main.tex", "First value 1. Then value 2.")
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["1", "2"]
    assert [item.value.kind for item in result.candidates] == [
        NumericKind.INTEGER,
        NumericKind.INTEGER,
    ]


def test_obvious_versions_files_urls_commands_and_hex_are_not_candidates(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        "v1.2 paper2.tex https://example.test/run/123 #A1B2C3 \\method2 text 42",
    )
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["42"]


def test_context_categories_environment_stack_and_command_are_recorded(tmp_path: Path) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        "text 1\n$2$\n\\command{3}\n\\begin{table} table 4 \\end{table}\n\\caption{caption 5}\n",
    )
    result = _scan(tmp_path)
    assert [item.context for item in result.candidates] == [
        LatexSyntacticContext.TEXT,
        LatexSyntacticContext.MATH,
        LatexSyntacticContext.COMMAND_ARGUMENT,
        LatexSyntacticContext.TABLE_ENVIRONMENT,
        LatexSyntacticContext.CAPTION,
    ]
    assert result.candidates[2].command == "command"
    assert result.candidates[3].environments == ("table",)
    assert result.candidates[4].command == "caption"


def test_command_arguments_are_retained_as_low_context_not_confirmed_claims(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "paper/main.tex",
        "\\setcounter{page}{7} \\url{https://example.test/99} visible 8",
    )
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["7", "8"]
    assert result.candidates[0].context is LatexSyntacticContext.COMMAND_ARGUMENT
    assert result.candidates[0].command == "setcounter"


def test_bom_crlf_positions_and_original_ranges_are_exact(tmp_path: Path) -> None:
    text = "alpha\r\nvalue 87.2\r\n尾部"
    _write(tmp_path, "paper/main.tex", text, bom=True)
    result = _scan(tmp_path)
    candidate = result.candidates[0]
    start = text.index("87.2")
    assert candidate.location.line == 2
    assert candidate.location.column == 7
    assert candidate.location.char_start == start
    assert candidate.location.char_end == start + 4
    assert candidate.location.end_line == 2
    assert candidate.location.end_column == 11
    assert result.graph.documents[0].byte_count == len(b"\xef\xbb\xbf" + text.encode("utf-8"))


def test_missing_include_does_not_discard_other_files(tmp_path: Path) -> None:
    _write(tmp_path, "paper/main.tex", "\\input{missing}\n\\input{good}\n1")
    _write(tmp_path, "paper/good.tex", "2")
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["2", "1"]
    assert any(item.code == "MPE_LATEX_INCLUDE_MISSING" for item in result.diagnostics)
    assert result.has_blocking_errors
    assert not result.complete


def test_include_cycle_is_reported_without_duplicate_candidates(tmp_path: Path) -> None:
    _write(tmp_path, "paper/main.tex", "1 \\input{a}")
    _write(tmp_path, "paper/a.tex", "2 \\include{main}")
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["2", "1"]
    assert any(item.code == "MPE_LATEX_INCLUDE_CYCLE" for item in result.diagnostics)
    assert len(result.graph.documents) == 2


@pytest.mark.parametrize(
    ("include", "code"),
    [
        ("../../outside", "MPE_LATEX_PATH_ESCAPE"),
        ("C:/outside.tex", "MPE_LATEX_PATH_ESCAPE"),
        ("image.png", "MPE_LATEX_INCLUDE_EXTENSION"),
        ("\\macro", "MPW_LATEX_DYNAMIC_INCLUDE"),
    ],
)
def test_include_boundary_failures_are_controlled(tmp_path: Path, include: str, code: str) -> None:
    _write(tmp_path, "paper/main.tex", f"1 \\input{{{include}}} 2")
    result = _scan(tmp_path)
    assert [item.raw_text for item in result.candidates] == ["1", "2"]
    assert any(item.code == code for item in result.diagnostics)


def test_excluded_include_is_not_read(tmp_path: Path) -> None:
    _write(tmp_path, "paper/main.tex", "1 \\input{generated/values} 2")
    _write(tmp_path, "paper/generated/values.tex", "99")
    result = _scan(tmp_path, excludes=("paper/generated/**",))
    assert [item.raw_text for item in result.candidates] == ["1", "2"]
    assert any(item.code == "MPW_LATEX_EXCLUDED_INCLUDE" for item in result.diagnostics)


def test_invalid_utf8_is_a_structured_diagnostic(tmp_path: Path) -> None:
    path = tmp_path / "paper" / "main.tex"
    path.parent.mkdir()
    path.write_bytes(b"\xff\xfe")
    result = _scan(tmp_path)
    assert not result.candidates
    assert result.diagnostics[0].code == "MPE_LATEX_ENCODING"
    assert not result.complete


def test_symlink_escape_is_rejected_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.tex"
    outside.write_text("99", encoding="utf-8")
    link = tmp_path / "paper" / "outside.tex"
    link.parent.mkdir()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    _write(tmp_path, "paper/main.tex", "\\input{outside}")
    result = _scan(tmp_path)
    assert any(item.code == "MPE_LATEX_PATH_ESCAPE" for item in result.diagnostics)
    assert not result.candidates


def test_file_size_total_size_file_count_depth_candidate_and_environment_limits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write(tmp_path, "paper/main.tex", "\\input{a}\n1 2 3")
    _write(tmp_path, "paper/a.tex", "\\input{b}\n4")
    _write(tmp_path, "paper/b.tex", "5")

    monkeypatch.setattr(latex_module, "MAX_LATEX_FILE_BYTES", 1)
    assert _scan(tmp_path).diagnostics[0].code == "MPE_LATEX_FILE_TOO_LARGE"

    monkeypatch.setattr(latex_module, "MAX_LATEX_FILE_BYTES", 5_000_000)
    monkeypatch.setattr(latex_module, "MAX_TOTAL_LATEX_BYTES", 12)
    assert any(item.code == "MPE_LATEX_TOTAL_SIZE" for item in _scan(tmp_path).diagnostics)

    monkeypatch.setattr(latex_module, "MAX_TOTAL_LATEX_BYTES", 25_000_000)
    monkeypatch.setattr(latex_module, "MAX_LATEX_FILES", 1)
    assert any(item.code == "MPE_LATEX_FILE_LIMIT" for item in _scan(tmp_path).diagnostics)

    monkeypatch.setattr(latex_module, "MAX_LATEX_FILES", 1_000)
    monkeypatch.setattr(latex_module, "MAX_LATEX_INCLUDE_DEPTH", 0)
    assert any(item.code == "MPE_LATEX_INCLUDE_DEPTH" for item in _scan(tmp_path).diagnostics)

    monkeypatch.setattr(latex_module, "MAX_LATEX_INCLUDE_DEPTH", 32)
    monkeypatch.setattr(latex_module, "MAX_LATEX_CANDIDATES", 2)
    candidate_limited = _scan(tmp_path)
    assert len(candidate_limited.candidates) == 2
    assert any(item.code == "MPE_LATEX_CANDIDATE_LIMIT" for item in candidate_limited.diagnostics)

    monkeypatch.setattr(latex_module, "MAX_LATEX_CANDIDATES", 100_000)
    monkeypatch.setattr(latex_module, "MAX_LATEX_ENVIRONMENT_DEPTH", 0)
    _write(tmp_path, "paper/main.tex", "\\begin{table}1\\end{table}")
    environment_limited = _scan(tmp_path)
    assert any(
        item.code == "MPE_LATEX_ENVIRONMENT_DEPTH" for item in environment_limited.diagnostics
    )
    assert environment_limited.candidates[0].context is LatexSyntacticContext.UNKNOWN
