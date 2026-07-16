"""Application-level Stage 4A scan orchestration."""

from decimal import Decimal
from pathlib import Path

import pytest

from metricproof.application.configuration import ProjectConfiguration
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.application.paper import scan_paper
from metricproof.domain.models import NumericValue, SourceLocation
from metricproof.domain.paper import (
    LatexSourceDocument,
    LatexSourceGraph,
    LatexSyntacticContext,
    NumericCandidateKind,
    PaperScanResult,
    PaperScanStatistics,
    RawNumericCandidate,
)


def _candidate(path: str, offset: int) -> RawNumericCandidate:
    return RawNumericCandidate(
        kind=NumericCandidateKind.VALUE,
        raw_text="1",
        value=NumericValue("1", Decimal("1")),
        location=SourceLocation(
            path=path,
            line=1,
            column=offset + 1,
            end_line=1,
            end_column=offset + 2,
            char_start=offset,
            char_end=offset + 1,
        ),
        context=LatexSyntacticContext.TEXT,
        environments=(),
        entry_paths=("paper/main.tex",),
        include_chain=("paper/main.tex", path) if path != "paper/main.tex" else (path,),
    )


class FakePaperScanner:
    def __init__(self) -> None:
        self.calls: list[tuple[Path, tuple[str, ...], tuple[str, ...]]] = []

    def scan(
        self,
        project_root: Path,
        entry_paths: tuple[str, ...],
        exclude_paths: tuple[str, ...] = (),
    ) -> PaperScanResult:
        self.calls.append((project_root, entry_paths, exclude_paths))
        candidates = (_candidate("paper/main.tex", 0), _candidate("paper/section.tex", 2))
        return PaperScanResult(
            graph=LatexSourceGraph(
                entry_paths=("paper/main.tex",),
                documents=(
                    LatexSourceDocument("paper/main.tex", 10, 10),
                    LatexSourceDocument("paper/section.tex", 10, 10),
                ),
                edges=(),
            ),
            candidates=candidates,
            diagnostics=(),
            statistics=PaperScanStatistics(2, 20, 2, 0),
            complete=True,
        )


def test_scan_paper_passes_validated_configuration_to_port(tmp_path: Path) -> None:
    scanner = FakePaperScanner()
    configuration = ProjectConfiguration(
        "1",
        (),
        exclude_paths=("build/**",),
        paper_paths=("paper/main.tex",),
    )
    result = scan_paper(tmp_path, configuration, scanner)
    assert result.statistics.candidate_count == 2
    assert scanner.calls == [
        (tmp_path, ("paper/main.tex",), ("build/**",)),
    ]


def test_scan_paper_filters_only_an_existing_graph_file(tmp_path: Path) -> None:
    result = scan_paper(
        tmp_path,
        ProjectConfiguration("1", (), paper_paths=("paper/main.tex",)),
        FakePaperScanner(),
        selected_file=r"paper\section.tex",
    )
    assert [item.location.path for item in result.candidates] == ["paper/section.tex"]
    assert result.statistics.candidate_count == 1


@pytest.mark.parametrize(
    "selected",
    ["", "../outside.tex", "C:/outside.tex", r"C:\outside.tex", "paper/main.pdf", "other.tex"],
)
def test_scan_paper_rejects_invalid_or_graph_external_selection(
    tmp_path: Path, selected: str
) -> None:
    with pytest.raises(ProjectConfigurationError):
        scan_paper(
            tmp_path,
            ProjectConfiguration("1", (), paper_paths=("paper/main.tex",)),
            FakePaperScanner(),
            selected_file=selected,
        )


def test_scan_paper_requires_explicit_entries(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigurationError, match="paper_paths"):
        scan_paper(tmp_path, ProjectConfiguration("1", ()), FakePaperScanner())
