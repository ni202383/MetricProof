"""Stage 4B2a deterministic Claim candidate classification behavior."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

from metricproof.adapters.config import YamlConfigurationRepository
from metricproof.adapters.latex import LocalLatexPaperScanner
from metricproof.application.claims import classify_claim_candidates
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.domain.claims import (
    ClaimDisposition,
    ClaimKind,
    classify_raw_candidates,
)
from metricproof.domain.models import NumericKind, NumericValue, SourceLocation
from metricproof.domain.paper import (
    LatexSourceDocument,
    LatexSourceGraph,
    LatexSyntacticContext,
    NumericCandidateKind,
    PaperScanResult,
    PaperScanStatistics,
    RawNumericCandidate,
)


def _scan_text(tmp_path: Path, text: str) -> PaperScanResult:
    (tmp_path / "main.tex").write_text(text, encoding="utf-8")
    return LocalLatexPaperScanner().scan(tmp_path, ("main.tex",))


def _classify_text(tmp_path: Path, text: str):
    return classify_raw_candidates(_scan_text(tmp_path, text)).classifications


@pytest.mark.parametrize(
    ("text", "raw", "disposition", "kind"),
    [
        (
            r"Accuracy reaches 87.2\%.",
            r"87.2\%",
            ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
            ClaimKind.DIRECT_RESULT,
        ),
        (
            "F1 score of 0.913.",
            "0.913",
            ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
            ClaimKind.DIRECT_RESULT,
        ),
        (
            "The method improves by 3.1 percentage points.",
            "3.1",
            ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
            ClaimKind.DERIVED_RESULT,
        ),
        (
            "误差相比基线提升 3.1 个百分点。",
            "3.1",
            ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
            ClaimKind.DERIVED_RESULT,
        ),
        (
            r"Accuracy is $0.872 \pm 0.004$.",
            r"0.872 \pm 0.004",
            ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
            ClaimKind.SUMMARY_STATISTIC,
        ),
        (
            "Training uses 100 epochs.",
            "100",
            ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM,
            ClaimKind.EXPERIMENT_QUANTITY,
        ),
        (
            "The batch size is 32.",
            "32",
            ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM,
            ClaimKind.EXPERIMENT_QUANTITY,
        ),
        (
            "We repeat 10 runs.",
            "10",
            ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM,
            ClaimKind.EXPERIMENT_QUANTITY,
        ),
    ],
)
def test_positive_and_experiment_quantity_examples(
    tmp_path: Path,
    text: str,
    raw: str,
    disposition: ClaimDisposition,
    kind: ClaimKind,
) -> None:
    matches = [item for item in _classify_text(tmp_path, text) if item.candidate.raw_text == raw]
    assert len(matches) == 1
    assert matches[0].disposition is disposition
    assert matches[0].kind is kind
    assert matches[0].evidence


def _candidate(
    *,
    raw: str = "12",
    prefix: str = "",
    suffix: str = "",
    command: str | None = None,
    context: LatexSyntacticContext = LatexSyntacticContext.TEXT,
    offset: int = 0,
) -> RawNumericCandidate:
    return RawNumericCandidate(
        kind=NumericCandidateKind.VALUE,
        raw_text=raw,
        value=NumericValue(
            raw_text=raw,
            parsed=Decimal(raw),
            kind=NumericKind.INTEGER
            if Decimal(raw) == Decimal(raw).to_integral()
            else NumericKind.DECIMAL,
        ),
        location=SourceLocation(
            path="paper/main.tex",
            line=1,
            column=offset + 1,
            end_line=1,
            end_column=offset + len(raw) + 1,
            char_start=offset,
            char_end=offset + len(raw),
        ),
        context=context,
        environments=(),
        entry_paths=("paper/main.tex",),
        include_chain=("paper/main.tex",),
        prefix=prefix,
        suffix=suffix,
        command=command,
    )


def _scan_for_candidates(*candidates: RawNumericCandidate) -> PaperScanResult:
    ordered = tuple(sorted(candidates, key=lambda item: item.location.char_start or -1))
    return PaperScanResult(
        graph=LatexSourceGraph(
            entry_paths=("paper/main.tex",),
            documents=(LatexSourceDocument("paper/main.tex", 100, 100),),
            edges=(),
        ),
        candidates=ordered,
        diagnostics=(),
        statistics=PaperScanStatistics(1, 100, len(ordered), 0),
        complete=True,
    )


@pytest.mark.parametrize(
    ("candidate", "reason"),
    [
        (
            _candidate(command="citep", context=LatexSyntacticContext.COMMAND_ARGUMENT),
            "CC_REFERENCE_ARGUMENT",
        ),
        (
            _candidate(command="ref", context=LatexSyntacticContext.COMMAND_ARGUMENT),
            "CC_REFERENCE_ARGUMENT",
        ),
        (
            _candidate(command="label", context=LatexSyntacticContext.COMMAND_ARGUMENT),
            "CC_REFERENCE_ARGUMENT",
        ),
        (
            _candidate(
                raw="0.8",
                prefix="width=",
                suffix=r"\textwidth",
                command="includegraphics",
                context=LatexSyntacticContext.COMMAND_ARGUMENT,
            ),
            "CC_LAYOUT_ARGUMENT",
        ),
        (
            _candidate(command="section", context=LatexSyntacticContext.COMMAND_ARGUMENT),
            "CC_STRUCTURE_ARGUMENT",
        ),
        (_candidate(prefix="Figure "), "CC_DOCUMENT_NUMBER"),
        (_candidate(prefix="https://example.org/item/"), "CC_URL_OR_IDENTIFIER"),
        (_candidate(raw="1.2", prefix="software version "), "CC_VERSION_OR_DATE"),
        (_candidate(raw="2026", prefix="copyright "), "CC_CONTEXTUAL_YEAR"),
        (_candidate(prefix="RGB color "), "CC_COLOR_OR_COORDINATE"),
    ],
)
def test_strong_negative_contexts_are_non_experiment(
    candidate: RawNumericCandidate,
    reason: str,
) -> None:
    result = classify_raw_candidates(_scan_for_candidates(candidate)).classifications[0]
    assert result.disposition is ClaimDisposition.NON_EXPERIMENT
    assert result.kind is ClaimKind.UNKNOWN
    assert reason in {item.reason_code for item in result.evidence}


def test_isolated_percent_and_math_constant_remain_ambiguous(tmp_path: Path) -> None:
    isolated = _classify_text(tmp_path, r"Observed 87.2\%.")[0]
    assert isolated.disposition is ClaimDisposition.AMBIGUOUS
    assert isolated.kind is ClaimKind.UNKNOWN

    other = tmp_path / "math"
    other.mkdir()
    mathematical = _classify_text(other, r"Let $x = 1.2$.")[0]
    assert mathematical.disposition is ClaimDisposition.AMBIGUOUS
    assert "CC_MATH_CONSTANT" in {item.reason_code for item in mathematical.evidence}


def test_parsed_degraded_and_unsupported_tables_have_distinct_strength(
    tmp_path: Path,
) -> None:
    scan = _scan_text(
        tmp_path,
        r"""
\begin{tabular}{cc}
Model & Accuracy \\
A & 87.2 \\
\end{tabular}
\begin{tabular}{cc}
\multirow{2}{*}{Model} & Accuracy \\
A & 86.1 \\
\end{tabular}
\begin{longtable}{cc}
Model & Accuracy \\
A & 85.0 \\
\end{longtable}
""",
    )
    by_raw = {
        item.candidate.raw_text: item for item in classify_raw_candidates(scan).classifications
    }
    assert by_raw["87.2"].disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM
    assert by_raw["86.1"].disposition is ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM
    assert by_raw["85.0"].disposition is not ClaimDisposition.LIKELY_EXPERIMENT_CLAIM
    reasons = {
        raw: {evidence.reason_code for evidence in item.evidence} for raw, item in by_raw.items()
    }
    assert "CC_PARSED_TABLE_DATA" in reasons["87.2"]
    assert "CC_DEGRADED_TABLE_DATA" in reasons["86.1"]
    assert "CC_UNSUPPORTED_TABLE" in reasons["85.0"]


def test_formatting_is_weak_candidate_specific_table_evidence(tmp_path: Path) -> None:
    classifications = _classify_text(
        tmp_path,
        r"\begin{tabular}{cc}A & 84.1 \\ B & \textbf{87.2} \\\end{tabular}",
    )
    by_raw = {item.candidate.raw_text: item for item in classifications}
    assert "CC_COMPARISON_FORMATTING" not in {
        evidence.reason_code for evidence in by_raw["84.1"].evidence
    }
    assert "CC_COMPARISON_FORMATTING" in {
        evidence.reason_code for evidence in by_raw["87.2"].evidence
    }
    assert by_raw["87.2"].score > by_raw["84.1"].score


def test_config_metric_alias_extends_builtins_and_is_strict(tmp_path: Path) -> None:
    paper = tmp_path / "paper"
    paper.mkdir()
    (paper / "main.tex").write_text("Balanced score reaches 0.91.", encoding="utf-8")
    config = tmp_path / ".metricproof" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        'schema_version: "1"\n'
        "paper_paths: [paper/main.tex]\n"
        "metric_aliases:\n"
        "  balanced_accuracy: [balanced score]\n",
        encoding="utf-8",
    )
    configuration = YamlConfigurationRepository().load(tmp_path)
    scan = LocalLatexPaperScanner().scan(tmp_path, configuration.paper_paths)
    classification = classify_claim_candidates(scan, configuration).classifications[0]
    assert configuration.metric_aliases == (("balanced_accuracy", ("balanced score",)),)
    assert classification.disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM
    assert classification.kind is ClaimKind.DIRECT_RESULT

    config.write_text(
        'schema_version: "1"\n'
        "paper_paths: [paper/main.tex]\n"
        "metric_aliases:\n"
        "  first: [shared]\n"
        "  second: [SHARED]\n",
        encoding="utf-8",
    )
    with pytest.raises(ProjectConfigurationError, match="already assigned"):
        YamlConfigurationRepository().load(tmp_path)


def test_classification_is_stable_does_not_merge_locations_or_mutate_scan() -> None:
    first = _candidate(raw="87.2", prefix="accuracy ", offset=20)
    second = _candidate(raw="87.2", prefix="accuracy ", offset=5)
    scan = _scan_for_candidates(first, second)
    before = deepcopy(scan)
    initial = classify_raw_candidates(scan)
    repeated = classify_raw_candidates(scan)
    assert initial == repeated
    assert scan == before
    assert len(initial.classifications) == 2
    assert [item.candidate.location.char_start for item in initial.classifications] == [5, 20]
    assert all(
        item.disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM
        for item in initial.classifications
    )


def test_generated_thousands_of_candidates_are_classified_once_and_partitioned() -> None:
    candidates = tuple(
        _candidate(raw=str(index + 1), prefix="accuracy ", offset=index * 8)
        for index in range(2_000)
    )
    result = classify_raw_candidates(_scan_for_candidates(*candidates))
    assert len(result.classifications) == 2_000
    assert len({item.candidate.location.char_start for item in result.classifications}) == 2_000
    assert result.statistics.total_count == 2_000
    assert (
        result.statistics.likely_count
        + result.statistics.possible_count
        + result.statistics.ambiguous_count
        + result.statistics.non_experiment_count
        == 2_000
    )
