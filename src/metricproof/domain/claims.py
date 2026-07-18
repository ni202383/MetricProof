"""Deterministic, explainable classification of raw paper numeric candidates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from re import Pattern

from metricproof.domain.models import InputDiagnostic, NumericKind, SourceLocation
from metricproof.domain.paper import (
    LatexFormattingKind,
    LatexSyntacticContext,
    LatexTable,
    LatexTableReliability,
    NumericCandidateKind,
    PaperScanResult,
    RawNumericCandidate,
    candidate_sort_key,
)

MIN_SCORE = 0
MAX_SCORE = 100
BASE_SCORE = 30
LIKELY_SCORE = 70
POSSIBLE_SCORE = 45
NON_EXPERIMENT_SCORE = 20

BUILTIN_METRIC_TERMS = (
    "accuracy",
    "acc",
    "precision",
    "recall",
    "f1 score",
    "f1",
    "auc",
    "average precision",
    "map",
    "ap",
    "iou",
    "bleu",
    "rouge",
    "perplexity",
    "loss",
    "error rate",
    "error",
    "latency",
    "throughput",
)

EXPERIMENT_QUANTITY_TERMS = (
    "epochs",
    "epoch",
    "batch size",
    "seed",
    "samples",
    "sample size",
    "parameters",
    "parameter count",
    "params",
    "flops",
    "gpus",
    "gpu",
    "runs",
    "run",
    "top-k",
    "top k",
    "split",
    "数据划分",
    "样本数",
    "参数量",
    "运行次数",
)

COMPARISON_TERMS = (
    "improves",
    "improved",
    "improvement",
    "increases",
    "increase",
    "decreases",
    "decrease",
    "gains",
    "gain",
    "drops",
    "drop",
    "outperforms",
    "compared with",
    "compared to",
    "percentage point",
    "percentage points",
    "relative improvement",
    "relative reduction",
    "提升",
    "下降",
    "优于",
    "相比",
    "百分点",
)

REFERENCE_COMMANDS = {
    "ref",
    "eqref",
    "pageref",
    "autoref",
    "label",
    "bibitem",
}
LAYOUT_COMMANDS = {
    "includegraphics",
    "vspace",
    "hspace",
    "setlength",
    "addtolength",
    "resizebox",
    "scalebox",
    "fontsize",
    "setcounter",
    "addtocounter",
    "raisebox",
    "rule",
    "color",
    "definecolor",
}
STRUCTURE_COMMANDS = {
    "section",
    "subsection",
    "subsubsection",
    "paragraph",
    "chapter",
    "part",
}
VISIBLE_TEXT_COMMANDS = {
    "caption",
    "text",
    "textbf",
    "underline",
    "emph",
    "textit",
    "textrm",
    "textsf",
    "texttt",
}

HARD_NEGATIVE_CODES = {
    "CC_REFERENCE_ARGUMENT",
    "CC_LAYOUT_ARGUMENT",
    "CC_STRUCTURE_ARGUMENT",
    "CC_LAYOUT_DIMENSION",
    "CC_DOCUMENT_NUMBER",
    "CC_URL_OR_IDENTIFIER",
    "CC_VERSION_OR_DATE",
    "CC_CONTEXTUAL_YEAR",
    "CC_COLOR_OR_COORDINATE",
}


class ClaimDisposition(StrEnum):
    """Review-oriented classification of a raw candidate."""

    LIKELY_EXPERIMENT_CLAIM = "likely_experiment_claim"
    POSSIBLE_EXPERIMENT_CLAIM = "possible_experiment_claim"
    AMBIGUOUS = "ambiguous"
    NON_EXPERIMENT = "non_experiment"


class ClaimKind(StrEnum):
    """Best deterministic type hint for a classified candidate."""

    DIRECT_RESULT = "direct_result"
    DERIVED_RESULT = "derived_result"
    SUMMARY_STATISTIC = "summary_statistic"
    EXPERIMENT_QUANTITY = "experiment_quantity"
    UNKNOWN = "unknown"


class ClaimConfidence(StrEnum):
    """Discrete evidence-strength level, not a calibrated probability."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class EvidenceDirection(StrEnum):
    """How one observed fact changes the classification score."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class ClaimEvidence:
    """One locatable, explainable rule contribution."""

    reason_code: str
    direction: EvidenceDirection
    score_impact: int
    explanation: str
    location: SourceLocation
    structural_context: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.reason_code or not self.explanation:
            raise ValueError("claim evidence requires a reason code and explanation")
        if self.direction is EvidenceDirection.POSITIVE and self.score_impact <= 0:
            raise ValueError("positive evidence requires a positive score impact")
        if self.direction is EvidenceDirection.NEGATIVE and self.score_impact >= 0:
            raise ValueError("negative evidence requires a negative score impact")
        if self.direction is EvidenceDirection.NEUTRAL and self.score_impact != 0:
            raise ValueError("neutral evidence must not change the score")


@dataclass(frozen=True, slots=True)
class ClaimCandidateClassification:
    """One non-persistent classification for one existing raw candidate."""

    candidate: RawNumericCandidate
    disposition: ClaimDisposition
    kind: ClaimKind
    score: int
    confidence: ClaimConfidence
    review_recommended: bool
    evidence: tuple[ClaimEvidence, ...]

    def __post_init__(self) -> None:
        if not MIN_SCORE <= self.score <= MAX_SCORE:
            raise ValueError("claim classification score must be between 0 and 100")
        expected_review = self.disposition in {
            ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
            ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM,
        }
        if self.review_recommended is not expected_review:
            raise ValueError("review recommendation must match the disposition")
        if not self.evidence:
            raise ValueError("claim classifications require explainable evidence")


@dataclass(frozen=True, slots=True)
class ClaimClassificationStatistics:
    """Exact partition counts for one classification pass."""

    total_count: int
    likely_count: int
    possible_count: int
    ambiguous_count: int
    non_experiment_count: int

    def __post_init__(self) -> None:
        values = (
            self.total_count,
            self.likely_count,
            self.possible_count,
            self.ambiguous_count,
            self.non_experiment_count,
        )
        if min(values) < 0:
            raise ValueError("classification statistics must be non-negative")
        partition = (
            self.likely_count
            + self.possible_count
            + self.ambiguous_count
            + self.non_experiment_count
        )
        if partition != self.total_count:
            raise ValueError("classification disposition counts must equal total_count")


@dataclass(frozen=True, slots=True)
class ClaimClassificationResult:
    """Stable classifications, statistics, and non-blocking diagnostics."""

    classifications: tuple[ClaimCandidateClassification, ...]
    statistics: ClaimClassificationStatistics
    diagnostics: tuple[InputDiagnostic, ...] = ()

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(self.classifications, key=lambda item: candidate_sort_key(item.candidate))
        )
        if ordered != self.classifications:
            raise ValueError("claim classifications must use stable candidate ordering")
        if len({candidate_sort_key(item.candidate) for item in self.classifications}) != len(
            self.classifications
        ):
            raise ValueError("each raw candidate may be classified only once")
        if self.statistics.total_count != len(self.classifications):
            raise ValueError("classification statistics must match classifications")


@dataclass(frozen=True, slots=True)
class _TermPattern:
    term: str
    pattern: Pattern[str] | None


@dataclass(frozen=True, slots=True)
class _TableCandidateContext:
    reliability: LatexTableReliability
    location: SourceLocation
    data_like: bool
    first_column_text_like: bool
    metric_term: str | None
    quantity_term: str | None
    formatting: tuple[LatexFormattingKind, ...]


def classify_raw_candidates(
    scan: PaperScanResult,
    *,
    additional_metric_terms: tuple[str, ...] = (),
) -> ClaimClassificationResult:
    """Classify prepared candidates without reading files or mutating the scan."""

    metric_patterns = _compile_terms((*BUILTIN_METRIC_TERMS, *additional_metric_terms))
    quantity_patterns = _compile_terms(EXPERIMENT_QUANTITY_TERMS)
    comparison_patterns = _compile_terms(COMPARISON_TERMS)
    table_contexts = _build_table_contexts(
        scan.tables, scan.candidates, metric_patterns, quantity_patterns
    )
    classifications = tuple(
        _classify_candidate(
            candidate,
            table_contexts.get(id(candidate)),
            metric_patterns,
            quantity_patterns,
            comparison_patterns,
        )
        for candidate in sorted(scan.candidates, key=candidate_sort_key)
    )
    return ClaimClassificationResult(
        classifications=classifications,
        statistics=_statistics(classifications),
    )


def _classify_candidate(
    candidate: RawNumericCandidate,
    table_context: _TableCandidateContext | None,
    metric_patterns: tuple[_TermPattern, ...],
    quantity_patterns: tuple[_TermPattern, ...],
    comparison_patterns: tuple[_TermPattern, ...],
) -> ClaimCandidateClassification:
    evidence: list[ClaimEvidence] = []
    context_text = f"{candidate.prefix}{candidate.raw_text}{candidate.suffix}"
    metric_context = _local_context(candidate, 64)
    quantity_context = _local_context(candidate, 32)
    comparison_context = _local_context(candidate, 64)
    metric_term = _find_term(metric_context, metric_patterns)
    quantity_term = _find_term(quantity_context, quantity_patterns)
    comparison_term = _find_term(comparison_context, comparison_patterns)
    derived_phrase = _is_derived_phrase(candidate.prefix, candidate.suffix)

    _add_command_evidence(candidate, evidence)
    _add_contextual_negative_evidence(candidate, context_text, evidence)

    if metric_term is not None and (table_context is None or table_context.metric_term is None):
        evidence.append(
            _positive(
                "CC_METRIC_CONTEXT",
                40,
                f"Nearby bounded text contains metric term {metric_term!r}.",
                candidate.location,
                f"metric_term={metric_term}",
            )
        )
    if comparison_term is not None:
        evidence.append(
            _positive(
                "CC_COMPARISON_LANGUAGE",
                20,
                f"Nearby bounded text contains comparison term {comparison_term!r}.",
                candidate.location,
                f"comparison_term={comparison_term}",
            )
        )
    if derived_phrase:
        evidence.append(
            _positive(
                "CC_DERIVED_EXPRESSION",
                20,
                "The number is locally attached to an improvement, reduction, or points phrase.",
                candidate.location,
            )
        )
    if quantity_term is not None and (table_context is None or table_context.quantity_term is None):
        evidence.append(
            _positive(
                "CC_EXPERIMENT_QUANTITY",
                15,
                f"Nearby bounded text contains experiment-quantity term {quantity_term!r}.",
                candidate.location,
                f"quantity_term={quantity_term}",
            )
        )

    if table_context is not None:
        _add_table_evidence(table_context, evidence)
        metric_term = metric_term or table_context.metric_term
        quantity_term = quantity_term or table_context.quantity_term

    if candidate.kind is NumericCandidateKind.MEAN_STD:
        evidence.append(
            _positive(
                "CC_COMPOUND_MEAN_STD",
                15,
                "The scanner retained this mean and uncertainty as one compound candidate.",
                candidate.location,
            )
        )
    elif candidate.value.kind is NumericKind.PERCENT:
        evidence.append(
            _positive(
                "CC_PERCENT_SHAPE",
                5,
                "Percentage form is weak supporting evidence only.",
                candidate.location,
            )
        )
    elif candidate.value.kind in {NumericKind.DECIMAL, NumericKind.SCIENTIFIC}:
        evidence.append(
            _positive(
                "CC_NUMERIC_SHAPE",
                3,
                "Decimal or scientific notation is weak supporting evidence only.",
                candidate.location,
            )
        )

    if not evidence:
        evidence.append(
            _neutral(
                "CC_INSUFFICIENT_CONTEXT",
                "No supported positive or negative classification context was observed.",
                candidate.location,
            )
        )

    hard_negative = any(item.reason_code in HARD_NEGATIVE_CODES for item in evidence)
    score = _clamp(BASE_SCORE + sum(item.score_impact for item in evidence))
    positive_strength = sum(max(0, item.score_impact) for item in evidence)
    negative_strength = sum(min(0, item.score_impact) for item in evidence)
    kind = _claim_kind(
        candidate,
        hard_negative=hard_negative,
        derived_phrase=derived_phrase,
        metric_term=metric_term,
        quantity_term=quantity_term,
    )
    disposition = _disposition(
        score,
        hard_negative=hard_negative,
        positive_strength=positive_strength,
        negative_strength=negative_strength,
        kind=kind,
    )
    confidence = _confidence(score, disposition)
    return ClaimCandidateClassification(
        candidate=candidate,
        disposition=disposition,
        kind=kind,
        score=score,
        confidence=confidence,
        review_recommended=disposition
        in {
            ClaimDisposition.LIKELY_EXPERIMENT_CLAIM,
            ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM,
        },
        evidence=tuple(evidence),
    )


def _add_command_evidence(
    candidate: RawNumericCandidate,
    evidence: list[ClaimEvidence],
) -> None:
    if candidate.context is not LatexSyntacticContext.COMMAND_ARGUMENT:
        return
    command = (candidate.command or "").casefold()
    if command.startswith("cite") or command in REFERENCE_COMMANDS:
        evidence.append(
            _negative(
                "CC_REFERENCE_ARGUMENT",
                -100,
                (
                    "The number is inside a citation, reference, label, or "
                    f"bibliography argument ({command})."
                ),
                candidate.location,
                f"command={command}",
            )
        )
    elif command in LAYOUT_COMMANDS:
        evidence.append(
            _negative(
                "CC_LAYOUT_ARGUMENT",
                -90,
                f"The number is inside a layout or sizing command argument ({command}).",
                candidate.location,
                f"command={command}",
            )
        )
    elif command in STRUCTURE_COMMANDS:
        evidence.append(
            _negative(
                "CC_STRUCTURE_ARGUMENT",
                -80,
                f"The number is inside a document-structure command argument ({command}).",
                candidate.location,
                f"command={command}",
            )
        )
    elif (
        candidate.context is LatexSyntacticContext.COMMAND_ARGUMENT
        and command not in VISIBLE_TEXT_COMMANDS
    ):
        evidence.append(
            _negative(
                "CC_GENERIC_COMMAND_ARGUMENT",
                -20,
                "Ordinary command arguments do not provide positive experimental evidence.",
                candidate.location,
                f"command={command or 'unknown'}",
            )
        )


def _add_contextual_negative_evidence(
    candidate: RawNumericCandidate,
    context_text: str,
    evidence: list[ClaimEvidence],
) -> None:
    folded = context_text.casefold()
    prefix = candidate.prefix.casefold()
    suffix = candidate.suffix.casefold()
    if re.search(
        r"(?:width|height|scale|spacing)\s*=\s*$",
        prefix,
    ) or re.match(r"\s*(?:pt|em|ex|mm|cm|in|\\textwidth|\\linewidth)\b", suffix):
        evidence.append(
            _negative(
                "CC_LAYOUT_DIMENSION",
                -80,
                "The number is attached to an explicit layout dimension or scale.",
                candidate.location,
            )
        )
    if re.search(r"(?:figure|fig\.|table|equation|eq\.|page|appendix)\s*$", prefix):
        evidence.append(
            _negative(
                "CC_DOCUMENT_NUMBER",
                -70,
                "The number is explicitly introduced as a document structure number.",
                candidate.location,
            )
        )
    if any(token in folded for token in ("http://", "https://", "doi:", "arxiv")):
        evidence.append(
            _negative(
                "CC_URL_OR_IDENTIFIER",
                -80,
                "The bounded context identifies a URL, DOI, or arXiv identifier.",
                candidate.location,
            )
        )
    if "version" in folded or re.search(r"\bv\s*$", prefix):
        evidence.append(
            _negative(
                "CC_VERSION_OR_DATE",
                -70,
                "The bounded context identifies a software or document version.",
                candidate.location,
            )
        )
    if _is_contextual_year(candidate, folded):
        evidence.append(
            _negative(
                "CC_CONTEXTUAL_YEAR",
                -65,
                "A four-digit year appears in citation, date, copyright, or dataset-year context.",
                candidate.location,
            )
        )
    if any(token in folded for token in ("rgb", "color", "coordinate", "axis")):
        evidence.append(
            _negative(
                "CC_COLOR_OR_COORDINATE",
                -70,
                "The bounded context identifies a color or coordinate value.",
                candidate.location,
            )
        )
    if candidate.context is LatexSyntacticContext.MATH:
        evidence.append(
            _negative(
                "CC_MATH_CONSTANT",
                -10,
                "A generic mathematical constant is ambiguous without experimental language.",
                candidate.location,
            )
        )


def _add_table_evidence(
    context: _TableCandidateContext,
    evidence: list[ClaimEvidence],
) -> None:
    if context.reliability is LatexTableReliability.PARSED and context.data_like:
        evidence.append(
            _positive(
                "CC_PARSED_TABLE_DATA",
                20,
                "The candidate is in a numeric-like cell of a reliably parsed table.",
                context.location,
            )
        )
    elif context.reliability is LatexTableReliability.DEGRADED and context.data_like:
        evidence.append(
            _positive(
                "CC_DEGRADED_TABLE_DATA",
                8,
                "The candidate is in a numeric-like cell, but table recovery is degraded.",
                context.location,
            )
        )
    elif context.reliability is LatexTableReliability.UNSUPPORTED:
        evidence.append(
            _negative(
                "CC_UNSUPPORTED_TABLE",
                -8,
                "Unsupported table structure cannot provide high-confidence structural evidence.",
                context.location,
            )
        )
    if context.first_column_text_like:
        evidence.append(
            _negative(
                "CC_TEXTUAL_FIRST_COLUMN",
                -25,
                (
                    "The candidate is in a text-like first-column cell, often "
                    "used for names or labels."
                ),
                context.location,
            )
        )
    if (
        context.metric_term is not None
        and context.reliability is not LatexTableReliability.UNSUPPORTED
    ):
        impact = 30 if context.reliability is LatexTableReliability.PARSED else 18
        evidence.append(
            _positive(
                "CC_TABLE_METRIC_CONTEXT",
                impact,
                f"Table caption or same-column text contains metric term {context.metric_term!r}.",
                context.location,
                f"metric_term={context.metric_term}",
                f"table_reliability={context.reliability.value}",
            )
        )
    if (
        context.quantity_term is not None
        and context.reliability is not LatexTableReliability.UNSUPPORTED
    ):
        evidence.append(
            _positive(
                "CC_TABLE_QUANTITY_CONTEXT",
                10,
                f"Table text contains experiment-quantity term {context.quantity_term!r}.",
                context.location,
                f"quantity_term={context.quantity_term}",
            )
        )
    if context.formatting:
        evidence.append(
            _positive(
                "CC_COMPARISON_FORMATTING",
                5,
                (
                    "Bold or underline formatting is weak evidence that the author "
                    "compares this value."
                ),
                context.location,
                *(f"formatting={item.value}" for item in context.formatting),
            )
        )


def _build_table_contexts(
    tables: tuple[LatexTable, ...],
    candidates: tuple[RawNumericCandidate, ...],
    metric_patterns: tuple[_TermPattern, ...],
    quantity_patterns: tuple[_TermPattern, ...],
) -> dict[int, _TableCandidateContext]:
    contexts: dict[int, _TableCandidateContext] = {}
    for table in tables:
        table_text = " ".join(
            value
            for value in (
                table.caption.normalized_text if table.caption is not None else "",
                table.label.normalized_text if table.label is not None else "",
            )
            if value
        )
        table_metric = _find_term(table_text, metric_patterns)
        table_quantity = _find_term(table_text, quantity_patterns)
        column_text: dict[int, list[str]] = {}
        for row in table.rows:
            for cell in row.cells:
                for column in range(
                    cell.logical_column_start,
                    cell.logical_column_start + cell.logical_column_span,
                ):
                    column_text.setdefault(column, []).append(cell.normalized_text)
        column_metrics = {
            column: _find_term(" ".join(texts), metric_patterns)
            for column, texts in column_text.items()
        }
        column_quantities = {
            column: _find_term(" ".join(texts), quantity_patterns)
            for column, texts in column_text.items()
        }
        for row in table.rows:
            for cell in row.cells:
                data_like = _cell_is_data_like(cell.normalized_text, cell.numeric_references)
                metric_term = table_metric or column_metrics.get(cell.logical_column_start)
                quantity_term = table_quantity or column_quantities.get(cell.logical_column_start)
                for reference in cell.numeric_references:
                    contexts.setdefault(
                        id(reference.candidate),
                        _TableCandidateContext(
                            reliability=table.reliability,
                            location=cell.location,
                            data_like=data_like,
                            first_column_text_like=(
                                cell.logical_column_start == 0 and not data_like
                            ),
                            metric_term=metric_term,
                            quantity_term=quantity_term,
                            formatting=reference.formatting,
                        ),
                    )
        if table.reliability is LatexTableReliability.UNSUPPORTED:
            for candidate in candidates:
                if _location_contains(table.location, candidate.location):
                    contexts.setdefault(
                        id(candidate),
                        _TableCandidateContext(
                            reliability=LatexTableReliability.UNSUPPORTED,
                            location=table.location,
                            data_like=False,
                            first_column_text_like=False,
                            metric_term=table_metric,
                            quantity_term=table_quantity,
                            formatting=(),
                        ),
                    )
    return contexts


def _location_contains(container: SourceLocation, item: SourceLocation) -> bool:
    if container.path != item.path:
        return False
    if container.char_start is None or container.char_end is None:
        return False
    if item.char_start is None or item.char_end is None:
        return False
    return container.char_start <= item.char_start and item.char_end <= container.char_end


def _cell_is_data_like(text: str, references: tuple[object, ...]) -> bool:
    remaining = text
    for reference in references:
        candidate = getattr(reference, "candidate", None)
        raw_text = getattr(candidate, "raw_text", "")
        if raw_text:
            remaining = remaining.replace(raw_text, " ")
    remaining = re.sub(r"[\s,;:+\-()/\\%±]+", "", remaining)
    return not remaining or not any(character.isalpha() for character in remaining)


def _claim_kind(
    candidate: RawNumericCandidate,
    *,
    hard_negative: bool,
    derived_phrase: bool,
    metric_term: str | None,
    quantity_term: str | None,
) -> ClaimKind:
    if hard_negative:
        return ClaimKind.UNKNOWN
    if candidate.kind is NumericCandidateKind.MEAN_STD:
        return ClaimKind.SUMMARY_STATISTIC
    if derived_phrase:
        return ClaimKind.DERIVED_RESULT
    if quantity_term is not None:
        return ClaimKind.EXPERIMENT_QUANTITY
    if metric_term is not None:
        return ClaimKind.DIRECT_RESULT
    return ClaimKind.UNKNOWN


def _disposition(
    score: int,
    *,
    hard_negative: bool,
    positive_strength: int,
    negative_strength: int,
    kind: ClaimKind,
) -> ClaimDisposition:
    if hard_negative:
        return ClaimDisposition.NON_EXPERIMENT
    if positive_strength >= 30 and negative_strength <= -30:
        return ClaimDisposition.AMBIGUOUS
    if kind is ClaimKind.EXPERIMENT_QUANTITY:
        return (
            ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM
            if score >= POSSIBLE_SCORE
            else ClaimDisposition.AMBIGUOUS
        )
    if score >= LIKELY_SCORE:
        return ClaimDisposition.LIKELY_EXPERIMENT_CLAIM
    if score >= POSSIBLE_SCORE:
        return ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM
    if score <= NON_EXPERIMENT_SCORE and negative_strength < 0:
        return ClaimDisposition.NON_EXPERIMENT
    return ClaimDisposition.AMBIGUOUS


def _confidence(score: int, disposition: ClaimDisposition) -> ClaimConfidence:
    if disposition is ClaimDisposition.AMBIGUOUS:
        return ClaimConfidence.LOW
    if disposition is ClaimDisposition.NON_EXPERIMENT:
        return ClaimConfidence.HIGH if score <= 10 else ClaimConfidence.MEDIUM
    if disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM:
        return ClaimConfidence.HIGH if score >= 80 else ClaimConfidence.MEDIUM
    return ClaimConfidence.MEDIUM if score >= 55 else ClaimConfidence.LOW


def _statistics(
    classifications: tuple[ClaimCandidateClassification, ...],
) -> ClaimClassificationStatistics:
    return ClaimClassificationStatistics(
        total_count=len(classifications),
        likely_count=sum(
            item.disposition is ClaimDisposition.LIKELY_EXPERIMENT_CLAIM for item in classifications
        ),
        possible_count=sum(
            item.disposition is ClaimDisposition.POSSIBLE_EXPERIMENT_CLAIM
            for item in classifications
        ),
        ambiguous_count=sum(
            item.disposition is ClaimDisposition.AMBIGUOUS for item in classifications
        ),
        non_experiment_count=sum(
            item.disposition is ClaimDisposition.NON_EXPERIMENT for item in classifications
        ),
    )


def _compile_terms(terms: tuple[str, ...]) -> tuple[_TermPattern, ...]:
    normalized = {" ".join(term.strip().casefold().split()) for term in terms if term.strip()}
    patterns: list[_TermPattern] = []
    for term in sorted(normalized, key=lambda value: (-len(value), value)):
        if any(ord(character) > 127 for character in term):
            patterns.append(_TermPattern(term, None))
        else:
            patterns.append(
                _TermPattern(
                    term,
                    re.compile(rf"(?<![\w]){re.escape(term)}(?![\w])", re.IGNORECASE),
                )
            )
    return tuple(patterns)


def _find_term(text: str, patterns: tuple[_TermPattern, ...]) -> str | None:
    folded = " ".join(text.casefold().split())
    for item in patterns:
        if item.pattern is None:
            if item.term in folded:
                return item.term
        elif item.pattern.search(folded) is not None:
            return item.term
    return None


def _local_context(candidate: RawNumericCandidate, radius: int) -> str:
    return f"{candidate.prefix[-radius:]}{candidate.raw_text}{candidate.suffix[:radius]}"


def _is_derived_phrase(prefix: str, suffix: str) -> bool:
    folded_prefix = " ".join(prefix.casefold().split())
    folded_suffix = " ".join(suffix.casefold().split())
    leading = re.search(
        r"(?:improvement|increase|decrease|gain|drop|reduction)"
        r"(?:\s+(?:of|by))?\s*$",
        folded_prefix,
    )
    chinese_leading = re.search(r"(?:提升|下降|增加|减少|降低)\s*$", folded_prefix)
    points_suffix = re.match(
        r"(?:percentage\s+points?|points?|个?百分点)",
        folded_suffix,
    )
    return leading is not None or chinese_leading is not None or points_suffix is not None


def _is_contextual_year(candidate: RawNumericCandidate, folded_context: str) -> bool:
    raw = candidate.raw_text.strip()
    if not re.fullmatch(r"\d{4}", raw):
        return False
    year = int(raw)
    if not 1900 <= year <= 2100:
        return False
    return any(
        token in folded_context
        for token in ("copyright", "published", "publication", "date", "dataset", "cite")
    )


def _positive(
    code: str,
    impact: int,
    explanation: str,
    location: SourceLocation,
    *context: str,
) -> ClaimEvidence:
    return ClaimEvidence(
        reason_code=code,
        direction=EvidenceDirection.POSITIVE,
        score_impact=impact,
        explanation=explanation,
        location=location,
        structural_context=tuple(context),
    )


def _negative(
    code: str,
    impact: int,
    explanation: str,
    location: SourceLocation,
    *context: str,
) -> ClaimEvidence:
    return ClaimEvidence(
        reason_code=code,
        direction=EvidenceDirection.NEGATIVE,
        score_impact=impact,
        explanation=explanation,
        location=location,
        structural_context=tuple(context),
    )


def _neutral(
    code: str,
    explanation: str,
    location: SourceLocation,
    *context: str,
) -> ClaimEvidence:
    return ClaimEvidence(
        reason_code=code,
        direction=EvidenceDirection.NEUTRAL,
        score_impact=0,
        explanation=explanation,
        location=location,
        structural_context=tuple(context),
    )


def _clamp(value: int) -> int:
    return max(MIN_SCORE, min(MAX_SCORE, value))
