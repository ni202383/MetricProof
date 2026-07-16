"""Controlled LaTeX file-graph and raw numeric candidate scanner."""

from __future__ import annotations

import re
from bisect import bisect_right
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath, PureWindowsPath

from metricproof.adapters.latex_tables import parse_latex_tables
from metricproof.adapters.limits import (
    MAX_LATEX_CANDIDATES,
    MAX_LATEX_CONTEXT_CHARS,
    MAX_LATEX_ENVIRONMENT_DEPTH,
    MAX_LATEX_FILE_BYTES,
    MAX_LATEX_FILES,
    MAX_LATEX_INCLUDE_ARGUMENT_CHARS,
    MAX_LATEX_INCLUDE_DEPTH,
    MAX_TOTAL_LATEX_BYTES,
)
from metricproof.domain.models import (
    DiagnosticKind,
    InputDiagnostic,
    NumericKind,
    NumericUnit,
    NumericValue,
    Severity,
    SourceLocation,
    diagnostic_sort_key,
    make_input_diagnostic,
)
from metricproof.domain.paper import (
    LatexIncludeEdge,
    LatexSourceDocument,
    LatexSourceGraph,
    LatexSyntacticContext,
    LatexTable,
    LatexTableReliability,
    NumericCandidateKind,
    PaperScanResult,
    PaperScanStatistics,
    RawNumericCandidate,
    candidate_sort_key,
    include_edge_sort_key,
    table_sort_key,
)

_NUMBER_RE = re.compile(r"[+-]?(?:(?:\d+\.\d+)|(?:\.\d+)|(?:\d+))(?:[eE][+-]?\d+)?")
_HEX_TOKEN_RE = re.compile(r"#[0-9A-Fa-f]{3,8}(?![0-9A-Fa-f])")
_CODE_ENVIRONMENTS = frozenset({"verbatim", "Verbatim", "lstlisting", "minted"})
_TABLE_ENVIRONMENTS = frozenset({"table", "table*", "tabular", "tabular*"})
_MATH_ENVIRONMENTS = frozenset(
    {
        "math",
        "displaymath",
        "equation",
        "equation*",
        "align",
        "align*",
        "gather",
        "gather*",
        "multline",
        "multline*",
    }
)
_SUPPRESSED_ARGUMENT_COMMANDS = frozenset(
    {
        "bibliography",
        "bibliographystyle",
        "documentclass",
        "href",
        "includegraphics",
        "label",
        "ref",
        "pageref",
        "url",
    }
)


@dataclass(frozen=True, slots=True)
class _IncludeDirective:
    command: str
    raw_path: str
    location: SourceLocation


@dataclass(frozen=True, slots=True)
class _ProvisionalCandidate:
    kind: NumericCandidateKind
    raw_text: str
    value: NumericValue
    location: SourceLocation
    context: LatexSyntacticContext
    environments: tuple[str, ...]
    prefix: str
    suffix: str
    command: str | None
    uncertainty: NumericValue | None


@dataclass(frozen=True, slots=True)
class _ParsedDocument:
    document: LatexSourceDocument
    includes: tuple[_IncludeDirective, ...]
    candidates: tuple[_ProvisionalCandidate, ...]
    text: str
    masked_text: str
    line_map: _LineMap

    def location(self, start: int, end: int) -> SourceLocation:
        return self.line_map.location(self.document.path, start, end)


@dataclass(frozen=True, slots=True)
class _Group:
    end_char: str
    command: str | None
    suppress: bool


@dataclass(frozen=True, slots=True)
class _NumberToken:
    raw_text: str
    numeric: NumericValue
    start: int
    end: int


class _LineMap:
    def __init__(self, text: str) -> None:
        self._starts = [0]
        self._starts.extend(index + 1 for index, character in enumerate(text) if character == "\n")

    def position(self, offset: int) -> tuple[int, int]:
        line_index = bisect_right(self._starts, offset) - 1
        return line_index + 1, offset - self._starts[line_index] + 1

    def location(self, path: str, start: int, end: int) -> SourceLocation:
        line, column = self.position(start)
        end_line, end_column = self.position(end)
        return SourceLocation(
            path=path,
            line=line,
            column=column,
            end_line=end_line,
            end_column=end_column,
            char_start=start,
            char_end=end,
        )


class LocalLatexPaperScanner:
    """Read and scan configured local LaTeX sources without executing TeX."""

    def scan(
        self,
        project_root: Path,
        entry_paths: tuple[str, ...],
        exclude_paths: tuple[str, ...] = (),
    ) -> PaperScanResult:
        session = _ScanSession(project_root, entry_paths, exclude_paths)
        return session.run()


class _ScanSession:
    def __init__(
        self,
        project_root: Path,
        entry_paths: tuple[str, ...],
        exclude_paths: tuple[str, ...],
    ) -> None:
        self.root = project_root.resolve(strict=True)
        self.entry_paths = tuple(sorted(set(entry_paths)))
        self.exclude_paths = tuple(sorted(set(exclude_paths)))
        self.documents: dict[str, _ParsedDocument] = {}
        self.edges: list[LatexIncludeEdge] = []
        self.diagnostics: list[InputDiagnostic] = []
        self.best_chains: dict[tuple[str, str], tuple[str, ...]] = {}
        self.physical_paths: dict[tuple[int, int], str] = {}
        self.total_bytes = 0
        self.remaining_candidates = MAX_LATEX_CANDIDATES
        self.complete = True
        self._candidate_limit_reported = False
        self._file_limit_reported = False
        self._total_limit_reported = False

    def run(self) -> PaperScanResult:
        for entry in self.entry_paths:
            resolved = self._resolve_declared_entry(entry)
            if resolved is None:
                continue
            canonical = self._canonical_path(resolved, entry)
            self._visit(
                entry=entry,
                resolved=resolved,
                display_path=canonical,
                chain=(canonical,),
                active=(),
                depth=0,
            )

        candidates = self._materialize_candidates()
        tables = self._materialize_tables(candidates)
        diagnostics_by_id = {item.diagnostic_id: item for item in self.diagnostics}
        diagnostics = tuple(sorted(diagnostics_by_id.values(), key=diagnostic_sort_key))
        documents = tuple(
            sorted(
                (parsed.document for parsed in self.documents.values()),
                key=lambda item: item.path,
            )
        )
        edges = tuple(sorted(self.edges, key=include_edge_sort_key))
        graph = LatexSourceGraph(
            entry_paths=self.entry_paths,
            documents=documents,
            edges=edges,
        )
        return PaperScanResult(
            graph=graph,
            candidates=candidates,
            diagnostics=diagnostics,
            statistics=PaperScanStatistics(
                scanned_file_count=len(documents),
                total_bytes=self.total_bytes,
                candidate_count=len(candidates),
                diagnostic_count=len(diagnostics),
                table_count=len(tables),
                parsed_table_count=sum(
                    item.reliability is LatexTableReliability.PARSED for item in tables
                ),
                degraded_table_count=sum(
                    item.reliability is LatexTableReliability.DEGRADED for item in tables
                ),
                unsupported_table_count=sum(
                    item.reliability is LatexTableReliability.UNSUPPORTED for item in tables
                ),
            ),
            complete=self.complete,
            tables=tables,
        )

    def _visit(
        self,
        *,
        entry: str,
        resolved: Path,
        display_path: str,
        chain: tuple[str, ...],
        active: tuple[str, ...],
        depth: int,
    ) -> None:
        chain_key = (entry, display_path)
        previous = self.best_chains.get(chain_key)
        if previous is not None and (len(previous), previous) <= (len(chain), chain):
            return
        self.best_chains[chain_key] = chain

        parsed = self.documents.get(display_path)
        if parsed is None:
            parsed = self._load_document(resolved, display_path)
            if parsed is None:
                return
            self.documents[display_path] = parsed

        next_active = (*active, display_path)
        for directive in parsed.includes:
            include = self._resolve_include(resolved.parent, directive)
            if include is None:
                continue
            target_resolved, target_hint = include
            target_display = self._canonical_path(target_resolved, target_hint)
            self.edges.append(
                LatexIncludeEdge(
                    source_path=display_path,
                    target_path=target_display,
                    command=directive.command,
                    location=directive.location,
                )
            )
            if target_display in next_active:
                cycle = (*next_active[next_active.index(target_display) :], target_display)
                self._add_diagnostic(
                    code="MPE_LATEX_INCLUDE_CYCLE",
                    severity=Severity.ERROR,
                    message="LaTeX include cycle was detected.",
                    location=directive.location,
                    remediation="remove one include edge from the reported cycle",
                    details=tuple(f"path={item}" for item in cycle),
                )
                self.complete = False
                continue
            if depth + 1 > MAX_LATEX_INCLUDE_DEPTH:
                self._add_diagnostic(
                    code="MPE_LATEX_INCLUDE_DEPTH",
                    severity=Severity.ERROR,
                    message=(
                        f"LaTeX include depth exceeds the fixed limit {MAX_LATEX_INCLUDE_DEPTH}."
                    ),
                    location=directive.location,
                    remediation="flatten the include graph or reduce nested includes",
                    details=(f"target={target_display}", f"depth={depth + 1}"),
                )
                self.complete = False
                continue
            self._visit(
                entry=entry,
                resolved=target_resolved,
                display_path=target_display,
                chain=(*chain, target_display),
                active=next_active,
                depth=depth + 1,
            )

    def _resolve_declared_entry(self, entry: str) -> Path | None:
        location = SourceLocation(path=".metricproof/config.yml", selector=f"paper_path={entry}")
        normalized = entry.replace("\\", "/")
        path = PurePosixPath(normalized)
        windows = PureWindowsPath(entry)
        if windows.is_absolute() or path.is_absolute() or ".." in path.parts:
            self._add_diagnostic(
                code="MPE_LATEX_PATH_ESCAPE",
                severity=Severity.ERROR,
                message=f"Invalid configured LaTeX entry path: {entry!r}.",
                location=location,
                remediation="use a project-relative .tex entry inside the project root",
            )
            self.complete = False
            return None
        if path.suffix.casefold() != ".tex":
            self._add_diagnostic(
                code="MPE_LATEX_ENTRY_EXTENSION",
                severity=Severity.ERROR,
                message=f"LaTeX entry does not use the .tex extension: {entry!r}.",
                location=location,
                remediation="declare a .tex entry file",
            )
            self.complete = False
            return None
        candidate = self.root / Path(*path.parts)
        return self._resolve_existing_file(
            candidate,
            entry,
            location,
            missing_code="MPE_LATEX_ENTRY_NOT_FOUND",
            missing_message=f"LaTeX entry file does not exist: {entry}.",
        )

    def _resolve_include(
        self,
        current_directory: Path,
        directive: _IncludeDirective,
    ) -> tuple[Path, str] | None:
        raw = directive.raw_path.strip()
        if not raw or len(raw) > MAX_LATEX_INCLUDE_ARGUMENT_CHARS:
            self._limitation(
                code="MPW_LATEX_DYNAMIC_INCLUDE",
                message="LaTeX include argument is empty or exceeds the supported static limit.",
                location=directive.location,
                remediation="use a short literal project-relative include path",
                details=(f"raw={raw!r}",),
            )
            return None
        if "\\" in raw or any(character in raw for character in "{}#$"):
            self._limitation(
                code="MPW_LATEX_DYNAMIC_INCLUDE",
                message="Dynamic or macro-based LaTeX include paths are not expanded.",
                location=directive.location,
                remediation="replace the include argument with a literal relative path",
                details=(f"raw={raw!r}",),
            )
            return None
        windows = PureWindowsPath(raw)
        posix = PurePosixPath(raw.replace("\\", "/"))
        if windows.is_absolute() or posix.is_absolute() or ".." in posix.parts:
            self._add_diagnostic(
                code="MPE_LATEX_PATH_ESCAPE",
                severity=Severity.ERROR,
                message=f"LaTeX include path escapes the project boundary: {raw!r}.",
                location=directive.location,
                remediation="use a relative include path contained in the project root",
            )
            self.complete = False
            return None
        if not posix.suffix:
            posix = posix.with_suffix(".tex")
        elif posix.suffix.casefold() != ".tex":
            self._add_diagnostic(
                code="MPE_LATEX_INCLUDE_EXTENSION",
                severity=Severity.ERROR,
                message=f"LaTeX include target is not a .tex file: {raw!r}.",
                location=directive.location,
                remediation="include a .tex source file",
            )
            self.complete = False
            return None
        candidate = current_directory / Path(*posix.parts)
        unresolved = candidate.resolve(strict=False)
        if not _is_within(unresolved, self.root):
            self._add_diagnostic(
                code="MPE_LATEX_PATH_ESCAPE",
                severity=Severity.ERROR,
                message=f"LaTeX include resolves outside the project root: {raw!r}.",
                location=directive.location,
                remediation="move the included file inside the project root",
            )
            self.complete = False
            return None
        hint = unresolved.relative_to(self.root).as_posix()
        if _matches_exclude(hint, self.exclude_paths):
            self._limitation(
                code="MPW_LATEX_EXCLUDED_INCLUDE",
                message=f"LaTeX include target is excluded by project configuration: {hint}.",
                location=directive.location,
                remediation="remove the exclusion or stop including that file",
                details=(f"target={hint}",),
            )
            return None
        resolved = self._resolve_existing_file(
            candidate,
            hint,
            directive.location,
            missing_code="MPE_LATEX_INCLUDE_MISSING",
            missing_message=f"LaTeX include target does not exist: {hint}.",
        )
        return None if resolved is None else (resolved, hint)

    def _resolve_existing_file(
        self,
        candidate: Path,
        display: str,
        location: SourceLocation,
        *,
        missing_code: str,
        missing_message: str,
    ) -> Path | None:
        try:
            resolved = candidate.resolve(strict=True)
        except FileNotFoundError:
            self._add_diagnostic(
                code=missing_code,
                severity=Severity.ERROR,
                message=missing_message,
                location=location,
                remediation="restore the file or correct the declared relative path",
                details=(f"path={display}",),
            )
            self.complete = False
            return None
        except OSError as error:
            self._add_diagnostic(
                code="MPE_LATEX_PATH_ERROR",
                severity=Severity.ERROR,
                message=f"LaTeX source path could not be resolved: {error}.",
                location=location,
                remediation="check the local path and filesystem permissions",
                details=(f"path={display}",),
            )
            self.complete = False
            return None
        if not _is_within(resolved, self.root):
            self._add_diagnostic(
                code="MPE_LATEX_PATH_ESCAPE",
                severity=Severity.ERROR,
                message=f"LaTeX source escapes the project root: {display}.",
                location=location,
                remediation="use a regular source file inside the project root",
            )
            self.complete = False
            return None
        if not resolved.is_file():
            self._add_diagnostic(
                code="MPE_LATEX_NOT_FILE",
                severity=Severity.ERROR,
                message=f"LaTeX source is not a regular file: {display}.",
                location=location,
                remediation="declare a regular .tex file",
            )
            self.complete = False
            return None
        return resolved

    def _canonical_path(self, resolved: Path, hint: str) -> str:
        stat = resolved.stat()
        physical = (stat.st_dev, stat.st_ino)
        existing = self.physical_paths.get(physical)
        if existing is not None:
            return existing
        canonical = resolved.relative_to(self.root).as_posix()
        self.physical_paths[physical] = canonical
        return canonical

    def _load_document(self, resolved: Path, display_path: str) -> _ParsedDocument | None:
        if len(self.documents) >= MAX_LATEX_FILES:
            if not self._file_limit_reported:
                self._add_diagnostic(
                    code="MPE_LATEX_FILE_LIMIT",
                    severity=Severity.ERROR,
                    message=f"LaTeX graph exceeds the fixed limit {MAX_LATEX_FILES} files.",
                    location=SourceLocation(path=display_path),
                    remediation="reduce the configured include graph",
                )
                self._file_limit_reported = True
            self.complete = False
            return None
        try:
            byte_count = resolved.stat().st_size
        except OSError as error:
            self._read_error(display_path, error)
            return None
        if byte_count > MAX_LATEX_FILE_BYTES:
            self._add_diagnostic(
                code="MPE_LATEX_FILE_TOO_LARGE",
                severity=Severity.ERROR,
                message=(
                    f"LaTeX source exceeds the fixed limit {MAX_LATEX_FILE_BYTES} bytes: "
                    f"{display_path}."
                ),
                location=SourceLocation(path=display_path),
                remediation="split or reduce the LaTeX source file",
            )
            self.complete = False
            return None
        if self.total_bytes + byte_count > MAX_TOTAL_LATEX_BYTES:
            if not self._total_limit_reported:
                self._add_diagnostic(
                    code="MPE_LATEX_TOTAL_SIZE",
                    severity=Severity.ERROR,
                    message=(
                        f"LaTeX graph exceeds the fixed total byte limit {MAX_TOTAL_LATEX_BYTES}."
                    ),
                    location=SourceLocation(path=display_path),
                    remediation="reduce the number or size of included LaTeX files",
                )
                self._total_limit_reported = True
            self.complete = False
            return None
        try:
            source_bytes = resolved.read_bytes()
        except OSError as error:
            self._read_error(display_path, error)
            return None
        try:
            text = source_bytes.decode("utf-8-sig")
        except UnicodeError as error:
            self._add_diagnostic(
                code="MPE_LATEX_ENCODING",
                severity=Severity.ERROR,
                message=f"LaTeX source is not valid UTF-8: {error}.",
                location=SourceLocation(path=display_path),
                remediation="save the source as UTF-8 or UTF-8 with BOM",
            )
            self.complete = False
            return None
        self.total_bytes += len(source_bytes)
        parsed, diagnostics, complete, omitted_location = _scan_document(
            text,
            display_path,
            self.remaining_candidates,
        )
        parsed = replace(
            parsed,
            document=LatexSourceDocument(
                path=display_path,
                byte_count=len(source_bytes),
                char_count=len(text),
            ),
        )
        self.diagnostics.extend(diagnostics)
        self.complete = self.complete and complete
        self.remaining_candidates -= len(parsed.candidates)
        if omitted_location is not None and not self._candidate_limit_reported:
            self._add_diagnostic(
                code="MPE_LATEX_CANDIDATE_LIMIT",
                severity=Severity.ERROR,
                message=(f"Raw numeric candidates exceed the fixed limit {MAX_LATEX_CANDIDATES}."),
                location=omitted_location,
                remediation="narrow the paper graph or split generated numeric content",
            )
            self._candidate_limit_reported = True
            self.complete = False
        return parsed

    def _read_error(self, display_path: str, error: OSError) -> None:
        self._add_diagnostic(
            code="MPE_LATEX_READ",
            severity=Severity.ERROR,
            message=f"LaTeX source could not be read: {error}.",
            location=SourceLocation(path=display_path),
            remediation="check local file permissions and accessibility",
        )
        self.complete = False

    def _materialize_candidates(self) -> tuple[RawNumericCandidate, ...]:
        candidates: list[RawNumericCandidate] = []
        for path, parsed in self.documents.items():
            chains = [
                (entry, chain)
                for (entry, document), chain in self.best_chains.items()
                if document == path
            ]
            if not chains:
                continue
            entry_paths = tuple(sorted(entry for entry, _ in chains))
            include_chain = min((chain for _, chain in chains), key=lambda item: (len(item), item))
            candidates.extend(
                RawNumericCandidate(
                    kind=item.kind,
                    raw_text=item.raw_text,
                    value=item.value,
                    uncertainty=item.uncertainty,
                    location=item.location,
                    context=item.context,
                    environments=item.environments,
                    command=item.command,
                    prefix=item.prefix,
                    suffix=item.suffix,
                    entry_paths=entry_paths,
                    include_chain=include_chain,
                )
                for item in parsed.candidates
            )
        return tuple(sorted(candidates, key=candidate_sort_key))

    def _materialize_tables(
        self,
        candidates: tuple[RawNumericCandidate, ...],
    ) -> tuple[LatexTable, ...]:
        candidates_by_path: dict[str, list[RawNumericCandidate]] = {}
        for candidate in candidates:
            candidates_by_path.setdefault(candidate.location.path, []).append(candidate)
        tables: list[LatexTable] = []
        for path, parsed in self.documents.items():
            result = parse_latex_tables(
                parsed.text,
                parsed.masked_text,
                path,
                tuple(candidates_by_path.get(path, ())),
                parsed.location,
            )
            tables.extend(result.tables)
            self.diagnostics.extend(result.diagnostics)
            self.complete = self.complete and result.complete
        return tuple(sorted(tables, key=table_sort_key))

    def _limitation(
        self,
        *,
        code: str,
        message: str,
        location: SourceLocation,
        remediation: str,
        details: tuple[str, ...] = (),
    ) -> None:
        diagnostic = make_input_diagnostic(
            code=code,
            severity=Severity.WARNING,
            message=message,
            location=location,
            remediation=remediation,
            evidence_details=details,
        )
        self.diagnostics.append(replace(diagnostic, kind=DiagnosticKind.LIMITATION))
        self.complete = False

    def _add_diagnostic(
        self,
        *,
        code: str,
        severity: Severity,
        message: str,
        location: SourceLocation,
        remediation: str,
        details: tuple[str, ...] = (),
    ) -> None:
        self.diagnostics.append(
            make_input_diagnostic(
                code=code,
                severity=severity,
                message=message,
                location=location,
                remediation=remediation,
                evidence_details=details,
            )
        )


def _scan_document(
    text: str,
    path: str,
    candidate_budget: int,
) -> tuple[_ParsedDocument, tuple[InputDiagnostic, ...], bool, SourceLocation | None]:
    line_map = _LineMap(text)
    masked = list(text)
    includes: list[_IncludeDirective] = []
    candidates: list[_ProvisionalCandidate] = []
    diagnostics: list[InputDiagnostic] = []
    environments: list[str] = []
    groups: list[_Group] = []
    math_stack: list[str] = []
    pending_command: tuple[str, int] | None = None
    last_command: tuple[str, int] | None = None
    context_uncertain = False
    complete = True
    omitted_location: SourceLocation | None = None
    index = 0

    while index < len(text):
        character = text[index]
        if character == "%" and not _is_escaped(text, index):
            pending_command = None
            newline = text.find("\n", index)
            comment_end = len(text) if newline < 0 else newline
            _mask_source_range(masked, index, comment_end)
            index = comment_end
            continue
        if character == "\\":
            command, command_end = _read_command(text, index)
            if command is None:
                index += 1
                continue
            if command in {"(", "["}:
                math_stack.append(command)
                pending_command = None
                index = command_end
                continue
            if command in {")", "]"}:
                opener = "(" if command == ")" else "["
                if math_stack and math_stack[-1] == opener:
                    math_stack.pop()
                pending_command = None
                index = command_end
                continue
            if command == "%":
                index = command_end
                continue
            if command == "verb":
                verb_end = _skip_verb(text, command_end)
                if verb_end is None:
                    diagnostics.append(
                        _limitation_diagnostic(
                            code="MPW_LATEX_UNCLOSED_VERB",
                            message="An unclosed \\verb span was ignored through end of file.",
                            location=line_map.location(path, index, min(command_end, len(text))),
                            remediation="close the \\verb span with the same delimiter",
                        )
                    )
                    complete = False
                    _mask_source_range(masked, index, len(text))
                    index = len(text)
                else:
                    _mask_source_range(masked, index, verb_end)
                    index = verb_end
                pending_command = None
                continue
            if command in {"begin", "end", "input", "include"}:
                argument = _read_braced_argument(text, command_end)
                if argument is None:
                    if command in {"input", "include"}:
                        diagnostics.append(
                            _limitation_diagnostic(
                                code="MPW_LATEX_DYNAMIC_INCLUDE",
                                message=(
                                    f"\\{command} without a static braced path is not expanded."
                                ),
                                location=line_map.location(path, index, command_end),
                                remediation="use a literal braced relative path",
                            )
                        )
                        complete = False
                    pending_command = None
                    last_command = (command, index)
                    index = command_end
                    continue
                raw_argument, _argument_start, argument_end = argument
                command_location = line_map.location(path, index, argument_end)
                if command in {"input", "include"}:
                    includes.append(
                        _IncludeDirective(
                            command=command,
                            raw_path=raw_argument,
                            location=command_location,
                        )
                    )
                else:
                    environment = raw_argument.strip()
                    if command == "begin" and environment in _CODE_ENVIRONMENTS:
                        marker = f"\\end{{{environment}}}"
                        closing = text.find(marker, argument_end)
                        if closing < 0:
                            diagnostics.append(
                                _limitation_diagnostic(
                                    code="MPW_LATEX_UNCLOSED_ENVIRONMENT",
                                    message=(
                                        f"Unclosed {environment} environment was ignored through "
                                        "end of file."
                                    ),
                                    location=command_location,
                                    remediation=f"add {marker}",
                                    details=(f"environment={environment}",),
                                )
                            )
                            complete = False
                            _mask_source_range(masked, index, len(text))
                            index = len(text)
                            continue
                        masked_end = closing + len(marker)
                        _mask_source_range(masked, index, masked_end)
                        index = masked_end
                        pending_command = None
                        last_command = (command, index)
                        continue
                    if command == "begin":
                        if len(environments) >= MAX_LATEX_ENVIRONMENT_DEPTH:
                            diagnostics.append(
                                make_input_diagnostic(
                                    code="MPE_LATEX_ENVIRONMENT_DEPTH",
                                    severity=Severity.ERROR,
                                    message=(
                                        "LaTeX environment nesting exceeds the fixed limit "
                                        f"{MAX_LATEX_ENVIRONMENT_DEPTH}."
                                    ),
                                    location=command_location,
                                    remediation="reduce nested LaTeX environments",
                                    evidence_details=(f"environment={environment}",),
                                )
                            )
                            complete = False
                            context_uncertain = True
                        else:
                            environments.append(environment)
                    elif environments:
                        if environments[-1] == environment:
                            environments.pop()
                        elif environment in environments:
                            del environments[environments.index(environment) :]
                pending_command = None
                last_command = (command, index)
                index = argument_end
                continue
            pending_command = (command, index)
            last_command = (command, index)
            index = command_end
            continue
        if character == "$" and not _is_escaped(text, index):
            marker = "$$" if text.startswith("$$", index) else "$"
            if math_stack and math_stack[-1] == marker:
                math_stack.pop()
            else:
                math_stack.append(marker)
            pending_command = None
            index += len(marker)
            continue
        if character in "{[":
            owner = pending_command[0] if pending_command is not None else _current_command(groups)
            groups.append(
                _Group(
                    end_char="}" if character == "{" else "]",
                    command=owner,
                    suppress=owner in _SUPPRESSED_ARGUMENT_COMMANDS,
                )
            )
            pending_command = None
            index += 1
            continue
        if character in "}]" and groups and groups[-1].end_char == character:
            closed = groups.pop()
            pending_command = (closed.command, index) if closed.command is not None else None
            index += 1
            continue
        if character.isspace():
            if character == "\n" and pending_command is not None:
                pending_command = None
            index += 1
            continue
        if any(group.suppress for group in groups):
            pending_command = None
            index += 1
            continue

        token = _read_number_token(text, index)
        if token is not None:
            if len(candidates) >= candidate_budget:
                if omitted_location is None:
                    omitted_location = line_map.location(path, token.start, token.end)
                index = token.end
                continue
            uncertainty: _NumberToken | None = None
            candidate_end = token.end
            separator_start = _skip_horizontal_space(text, token.end)
            separator_end = _mean_std_separator_end(text, separator_start)
            if separator_end is not None:
                uncertainty_start = _skip_horizontal_space(text, separator_end)
                uncertainty = _read_number_token(text, uncertainty_start)
                if uncertainty is not None:
                    candidate_end = uncertainty.end
            context = _syntactic_context(
                environments,
                groups,
                math_stack,
                context_uncertain=context_uncertain,
            )
            command = _current_command(groups)
            if command is None and last_command is not None:
                name, command_offset = last_command
                if command_offset >= text.rfind("\n", 0, token.start) and (
                    token.start - command_offset <= MAX_LATEX_CONTEXT_CHARS
                ):
                    command = name
            raw_text = text[token.start : candidate_end]
            candidates.append(
                _ProvisionalCandidate(
                    kind=(
                        NumericCandidateKind.MEAN_STD
                        if uncertainty is not None
                        else NumericCandidateKind.VALUE
                    ),
                    raw_text=raw_text,
                    value=token.numeric,
                    uncertainty=uncertainty.numeric if uncertainty is not None else None,
                    location=line_map.location(path, token.start, candidate_end),
                    context=context,
                    environments=tuple(environments),
                    command=command,
                    prefix=text[max(0, token.start - MAX_LATEX_CONTEXT_CHARS) : token.start],
                    suffix=text[
                        candidate_end : min(
                            len(text),
                            candidate_end + MAX_LATEX_CONTEXT_CHARS,
                        )
                    ],
                )
            )
            pending_command = None
            index = candidate_end
            continue
        pending_command = None
        index += 1

    document = LatexSourceDocument(
        path=path,
        byte_count=len(text.encode("utf-8")),
        char_count=len(text),
    )
    return (
        _ParsedDocument(
            document=document,
            includes=tuple(includes),
            candidates=tuple(candidates),
            text=text,
            masked_text="".join(masked),
            line_map=line_map,
        ),
        tuple(diagnostics),
        complete,
        omitted_location,
    )


def _read_command(text: str, start: int) -> tuple[str | None, int]:
    if start + 1 >= len(text):
        return None, start + 1
    index = start + 1
    if text[index].isalpha() or text[index] == "@":
        index += 1
        while index < len(text) and (text[index].isalpha() or text[index] == "@"):
            index += 1
        command = text[start + 1 : index]
        if command == "verb" and index < len(text) and text[index] == "*":
            index += 1
        return command, index
    return text[index], index + 1


def _read_braced_argument(text: str, start: int) -> tuple[str, int, int] | None:
    index = start
    while index < len(text) and text[index].isspace():
        index += 1
    if index >= len(text) or text[index] != "{":
        return None
    argument_start = index + 1
    closing = text.find("}", argument_start)
    if closing < 0:
        return None
    return text[argument_start:closing], argument_start, closing + 1


def _skip_verb(text: str, start: int) -> int | None:
    if start >= len(text) or text[start].isspace():
        return None
    delimiter = text[start]
    closing = text.find(delimiter, start + 1)
    return None if closing < 0 else closing + 1


def _read_number_token(text: str, start: int) -> _NumberToken | None:
    match = _NUMBER_RE.match(text, start)
    if match is None or not _valid_number_boundaries(text, match.start(), match.end()):
        return None
    if _inside_url_or_filename(text, match.start()) or _inside_hex_token(text, match.start()):
        return None
    raw_number = match.group(0)
    end = match.end()
    percent = False
    if text.startswith("\\%", end):
        end += 2
        percent = True
    elif end < len(text) and text[end] == "%":
        end += 1
        percent = True
    try:
        parsed = Decimal(raw_number)
    except InvalidOperation:
        return None
    if not parsed.is_finite():
        return None
    decimal_places = _decimal_places(raw_number)
    lexical_kind = (
        NumericKind.PERCENT
        if percent
        else NumericKind.SCIENTIFIC
        if "e" in raw_number.casefold()
        else NumericKind.DECIMAL
        if "." in raw_number
        else NumericKind.INTEGER
    )
    raw_text = text[start:end]
    numeric = NumericValue(
        raw_text=raw_text,
        parsed=parsed,
        unit=NumericUnit.RATIO if percent else NumericUnit.SCALAR,
        kind=lexical_kind,
        decimal_places=decimal_places,
        scale=Decimal("0.01") if percent else Decimal("1"),
    )
    return _NumberToken(raw_text=raw_text, numeric=numeric, start=start, end=end)


def _valid_number_boundaries(text: str, start: int, end: int) -> bool:
    if start > 0:
        previous = text[start - 1]
        if previous.isalnum() or previous in {"_", "."}:
            return False
    if end < len(text):
        following = text[end]
        if following.isalpha() or following == "_":
            return False
        if following == "." and end + 1 < len(text) and text[end + 1].isdigit():
            return False
    return True


def _inside_url_or_filename(text: str, start: int) -> bool:
    token_start = start
    while token_start > 0 and not text[token_start - 1].isspace():
        if text[token_start - 1] in "{}[]()<>\\\"'":
            break
        token_start -= 1
    token_end = start
    while token_end < len(text) and not text[token_end].isspace():
        if text[token_end] in "{}[]()<>\\\"'":
            break
        token_end += 1
    token = text[token_start:token_end]
    folded = token.casefold()
    if "://" in token or folded.startswith("www."):
        return True
    cleaned = token.strip(".,;:!?")
    candidate_path = PurePosixPath(cleaned)
    suffix = candidate_path.suffix
    return bool(
        suffix
        and any(character.isalpha() for character in suffix)
        and (
            any(character.isalpha() for character in candidate_path.stem)
            or "/" in cleaned
            or "\\" in cleaned
        )
    )


def _inside_hex_token(text: str, start: int) -> bool:
    hash_index = text.rfind("#", max(0, start - 8), start + 1)
    if hash_index < 0:
        return False
    match = _HEX_TOKEN_RE.match(text, hash_index)
    return match is not None and match.start() <= start < match.end()


def _decimal_places(raw_text: str) -> int:
    mantissa = re.split("[eE]", raw_text.lstrip("+-"), maxsplit=1)[0]
    return 0 if "." not in mantissa else len(mantissa.partition(".")[2])


def _skip_horizontal_space(text: str, start: int) -> int:
    index = start
    while index < len(text) and text[index] in {" ", "\t"}:
        index += 1
    return index


def _mean_std_separator_end(text: str, start: int) -> int | None:
    if text.startswith("±", start):
        return start + 1
    if text.startswith("\\pm", start):
        return start + 3
    return None


def _current_command(groups: list[_Group]) -> str | None:
    return next((group.command for group in reversed(groups) if group.command is not None), None)


def _syntactic_context(
    environments: list[str],
    groups: list[_Group],
    math_stack: list[str],
    *,
    context_uncertain: bool,
) -> LatexSyntacticContext:
    if context_uncertain:
        return LatexSyntacticContext.UNKNOWN
    command = _current_command(groups)
    if command == "caption":
        return LatexSyntacticContext.CAPTION
    if any(environment in _TABLE_ENVIRONMENTS for environment in environments):
        return LatexSyntacticContext.TABLE_ENVIRONMENT
    if command is not None:
        return LatexSyntacticContext.COMMAND_ARGUMENT
    if math_stack or any(environment in _MATH_ENVIRONMENTS for environment in environments):
        return LatexSyntacticContext.MATH
    return LatexSyntacticContext.TEXT


def _is_escaped(text: str, index: int) -> bool:
    backslashes = 0
    cursor = index - 1
    while cursor >= 0 and text[cursor] == "\\":
        backslashes += 1
        cursor -= 1
    return backslashes % 2 == 1


def _matches_exclude(path: str, patterns: tuple[str, ...]) -> bool:
    candidate = Path(path)
    return any(candidate.match(pattern) for pattern in patterns)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _limitation_diagnostic(
    *,
    code: str,
    message: str,
    location: SourceLocation,
    remediation: str,
    details: tuple[str, ...] = (),
) -> InputDiagnostic:
    diagnostic = make_input_diagnostic(
        code=code,
        severity=Severity.WARNING,
        message=message,
        location=location,
        remediation=remediation,
        evidence_details=details,
    )
    return replace(diagnostic, kind=DiagnosticKind.LIMITATION)


def _mask_source_range(masked: list[str], start: int, end: int) -> None:
    for index in range(start, end):
        if masked[index] not in {"\r", "\n"}:
            masked[index] = " "
