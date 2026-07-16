"""Pure Stage 4A domain-model invariants."""

from decimal import Decimal

import pytest

from metricproof.domain.models import NumericKind, NumericUnit, NumericValue, SourceLocation
from metricproof.domain.paper import (
    LatexCellFormatting,
    LatexCellNumericReference,
    LatexColumnSpec,
    LatexFormattingKind,
    LatexIncludeEdge,
    LatexSourceDocument,
    LatexSourceGraph,
    LatexSyntacticContext,
    LatexTable,
    LatexTableCell,
    LatexTableKind,
    LatexTableReliability,
    LatexTableRow,
    NumericCandidateKind,
    PaperScanResult,
    PaperScanStatistics,
    RawNumericCandidate,
)


def _location() -> SourceLocation:
    return SourceLocation(
        path="paper/main.tex",
        line=1,
        column=1,
        end_line=1,
        end_column=5,
        char_start=0,
        char_end=4,
    )


def test_numeric_value_preserves_canonical_percent_and_sign() -> None:
    value = NumericValue(
        raw_text="+87.2\\%",
        parsed=Decimal("87.2"),
        unit=NumericUnit.RATIO,
        kind=NumericKind.PERCENT,
        decimal_places=1,
        scale=Decimal("0.01"),
    )
    assert value.canonical == Decimal("0.872")
    assert value.sign == "+"


def test_numeric_value_keeps_stage3_constructor_compatibility() -> None:
    value = NumericValue("1.25", Decimal("1.25"))
    assert value.canonical == Decimal("1.25")
    assert value.unit is NumericUnit.SCALAR


@pytest.mark.parametrize(
    "kwargs",
    [
        {"canonical": Decimal("9")},
        {"decimal_places": -1},
        {"scale": Decimal("NaN")},
        {"sign": "positive"},
    ],
)
def test_numeric_value_rejects_inconsistent_extensions(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        NumericValue("1", Decimal("1"), **kwargs)  # pyright: ignore[reportArgumentType]


def test_raw_candidate_and_graph_require_stable_provenance() -> None:
    location = _location()
    candidate = RawNumericCandidate(
        kind=NumericCandidateKind.VALUE,
        raw_text="87.2",
        value=NumericValue("87.2", Decimal("87.2")),
        location=location,
        context=LatexSyntacticContext.TEXT,
        environments=(),
        entry_paths=("paper/main.tex",),
        include_chain=("paper/main.tex",),
    )
    edge = LatexIncludeEdge(
        source_path="paper/main.tex",
        target_path="paper/section.tex",
        command="input",
        location=location,
    )
    graph = LatexSourceGraph(
        entry_paths=("paper/main.tex",),
        documents=(
            LatexSourceDocument("paper/main.tex", 10, 10),
            LatexSourceDocument("paper/section.tex", 5, 5),
        ),
        edges=(edge,),
    )
    result = PaperScanResult(
        graph=graph,
        candidates=(candidate,),
        diagnostics=(),
        statistics=PaperScanStatistics(2, 15, 1, 0),
        complete=True,
    )
    assert not result.has_blocking_errors


def test_mean_std_candidate_requires_uncertainty() -> None:
    with pytest.raises(ValueError):
        RawNumericCandidate(
            kind=NumericCandidateKind.MEAN_STD,
            raw_text="1 ± 2",
            value=NumericValue("1", Decimal("1")),
            location=_location(),
            context=LatexSyntacticContext.TEXT,
            environments=(),
            entry_paths=("paper/main.tex",),
            include_chain=("paper/main.tex",),
        )


def test_graph_rejects_unstable_document_order() -> None:
    with pytest.raises(ValueError):
        LatexSourceGraph(
            entry_paths=("paper/main.tex",),
            documents=(
                LatexSourceDocument("z.tex", 1, 1),
                LatexSourceDocument("a.tex", 1, 1),
            ),
            edges=(),
        )


def test_source_location_allows_exact_zero_width_empty_cell_range() -> None:
    location = SourceLocation(
        path="paper/main.tex",
        line=1,
        column=4,
        end_line=1,
        end_column=4,
        char_start=3,
        char_end=3,
    )
    assert location.char_start == location.char_end == 3


def test_table_models_reference_existing_candidate_and_validate_logical_width() -> None:
    location = _location()
    candidate = RawNumericCandidate(
        kind=NumericCandidateKind.VALUE,
        raw_text="87.2",
        value=NumericValue("87.2", Decimal("87.2")),
        location=location,
        context=LatexSyntacticContext.TABLE_ENVIRONMENT,
        environments=("tabular",),
        entry_paths=("paper/main.tex",),
        include_chain=("paper/main.tex",),
    )
    formatting = LatexCellFormatting(
        kind=LatexFormattingKind.BOLD,
        location=location,
        content_location=location,
    )
    reference = LatexCellNumericReference(
        candidate=candidate,
        formatting=(LatexFormattingKind.BOLD,),
    )
    cell = LatexTableCell(
        physical_index=0,
        logical_column_start=0,
        logical_column_span=1,
        multicolumn_format=None,
        location=location,
        content_location=location,
        raw_latex="87.2",
        normalized_text="87.2",
        is_empty=False,
        numeric_references=(reference,),
        formatting=(formatting,),
        reliability=LatexTableReliability.PARSED,
    )
    row = LatexTableRow(
        row_index=0,
        location=location,
        cells=(cell,),
        logical_column_count=1,
        structure_markers=(),
        reliability=LatexTableReliability.PARSED,
    )
    table = LatexTable(
        environment=LatexTableKind.TABULAR,
        location=location,
        container_environment=None,
        container_location=None,
        caption=None,
        label=None,
        column_spec=LatexColumnSpec("{c}", location, 1),
        rows=(row,),
        structure_markers=(),
        diagnostics=(),
        reliability=LatexTableReliability.PARSED,
    )
    statistics = PaperScanStatistics(1, 10, 1, 0, 1, 1, 0, 0)
    result = PaperScanResult(
        graph=LatexSourceGraph(
            entry_paths=("paper/main.tex",),
            documents=(LatexSourceDocument("paper/main.tex", 10, 10),),
            edges=(),
        ),
        candidates=(candidate,),
        diagnostics=(),
        statistics=statistics,
        complete=True,
        tables=(table,),
    )
    reference_candidate = result.tables[0].rows[0].cells[0].numeric_references[0].candidate
    assert reference_candidate is candidate
    assert result.tables[0].expected_column_count == 1


def test_scan_statistics_require_complete_table_reliability_partition() -> None:
    with pytest.raises(ValueError, match="reliability counts"):
        PaperScanStatistics(1, 10, 0, 0, table_count=1)


def test_row_rejects_logical_count_that_disagrees_with_cell_spans() -> None:
    location = _location()
    cell = LatexTableCell(
        physical_index=0,
        logical_column_start=0,
        logical_column_span=2,
        multicolumn_format="c",
        location=location,
        content_location=location,
        raw_latex="value",
        normalized_text="value",
        is_empty=False,
        numeric_references=(),
        formatting=(),
        reliability=LatexTableReliability.PARSED,
    )
    with pytest.raises(ValueError, match="logical column count"):
        LatexTableRow(
            row_index=0,
            location=location,
            cells=(cell,),
            logical_column_count=1,
            structure_markers=(),
            reliability=LatexTableReliability.PARSED,
        )
