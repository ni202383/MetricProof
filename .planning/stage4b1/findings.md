# Stage 4B1 Findings

## Task and repository state

- Stage 4B1 establishes table structure facts only; it must not enter Claim classification, Claim IDs, experiment links, or rule checks.
- The initial worktree was clean. Root planning files preserve older phases, and .planning/stage4a/ contains the immediate handoff.
- Stage 4A already provides RawNumericCandidate, exact character ranges, LaTeX environment context, source documents, include graph, structured diagnostics, and centralized limits.

## Reusable Stage 4A boundaries

- A deterministic state machine already handles comments, verb, and code-environment masking.
- SourceLocation already includes file, start/end lines and columns, and character ranges.
- RawNumericCandidate already stores deterministic values, contexts, and provenance and must not be recreated by table parsing.
- InputDiagnostic, evidence, stable sorting, application ports, and CLI exit handling can be extended.
- Fixed resource limits live in src/metricproof/adapters/limits.py.

## Initial implementation direction

- Parse each existing LatexSourceDocument using Stage 4A prepared source/masking state rather than a second file read or coordinate system.
- Row/cell scanning must explicitly track brace depth, math context, nested environments, escaping, and the current tabular level; string split is invalid.
- Formatting should be associated by checking candidate ranges against supported command content ranges.
- multirow is an explicit limitation; basic multicolumn contributes to logical column counts; unknown column specs must not be guessed.

## Formal design constraints

- AGENTS.md requires structured diagnostics for recoverable parse errors, controlled degradation for unsupported syntax, deterministic ordering, and project-relative domain paths.
- SPEC.md currently says multicolumn is not guaranteed; Stage 4B1 must minimally update it to distinguish supported basic form from degraded complex forms.
- ARCHITECTURE.md currently says ScanPaper has no table semantics; after implementation it must describe basic structure facts in the same PaperScanResult while preserving the PaperScanner port boundary.
- docs/data-model.md has an older PaperTable/TableCell sketch with table_id, headers, row headers, column headers, and cell-wide format booleans. That conflicts with Stage 4B1 and should become a minimal LatexTable family without Claim or header semantics.
- Domain collections should remain immutable tuples with stable ordering and explicit types, never unbounded dictionaries or third-party AST objects.


## Compatibility and documentation findings

- docs/rule-semantics.md confirms future WRONG_BEST_MARK must skip unreliable structures. Stage 4B1 should expose reliability and formatting facts only, without computing best or second-best sets.
- docs/example-workflow.md and docs/status.md are explicitly Stage 4A and must be advanced to Stage 4B1 once the implementation is verified.
- Existing scan behavior includes --show-all and --file. New --show-tables and richer JSON must preserve those options, stdout/stderr separation, read-only behavior, and existing candidate counts.
- The stable public handoff includes NumericKind, NumericUnit, LatexSyntacticContext, NumericCandidateKind, RawNumericCandidate, LatexSourceDocument, LatexIncludeEdge, LatexSourceGraph, PaperScanStatistics, PaperScanResult, PaperScanner, scan_paper, LocalLatexPaperScanner, and metricproof scan.
- Current code is compact: the LaTeX implementation is concentrated in adapters/latex.py, domain/paper.py, application/paper.py and ports.py, with focused paper/scanner/CLI/generated tests. New modules should be created only if responsibilities become genuinely clearer.

## Domain and application inspection

- domain/paper.py is one compact immutable model module. PaperScanStatistics currently has four counts and PaperScanResult has graph, candidates, diagnostics, statistics, and complete.
- scan_paper reconstructs PaperScanResult when --file is used, so table filtering and new statistics must be handled there to avoid returning tables from other graph files.
- PaperScanner already returns PaperScanResult and needs no new port method; table parsing belongs inside the concrete scanner result construction.
- adapters/limits.py is the required centralized location for table-count, row, cell, nesting, cell-length, and multicolumn-span limits.
- Adding table fields with defaults may preserve source compatibility for test fakes and callers; constructor ordering and strict immutable validation need careful review before deciding.

## Scanner shape

- adapters/latex.py is 1,119 lines. _ScanSession owns file graph traversal and materialization; _scan_document is the per-document deterministic lexer/state machine.
- The existing scanner already recognizes table/table*/tabular/tabular* only as syntactic context and keeps environment stacks; it does not retain source text in the public LatexSourceDocument model.
- Table parsing can reuse the _ParsedDocument objects retained inside _ScanSession before result construction, avoiding a second physical read and keeping the same character coordinate system.
- A focused adapters/latex_tables.py helper is likely justified to keep adapters/latex.py from becoming a monolith, provided it receives prepared source text/candidate ranges and returns domain objects without file I/O.

## Detailed scanner findings

- _ScanSession._load_document reads each file once, decodes UTF-8, calls _scan_document, stores _ParsedDocument, and later materializes public candidates with include provenance.
- _ParsedDocument currently stores only document metadata, include directives, and provisional candidates. To parse tables without rereading, it should also carry prepared table structures or a length-preserving masked source produced during the same scan.
- _scan_document already jumps over comments and code environments but does not retain a mask. Extending that same state machine to blank ignored ranges preserves one authoritative comment/code interpretation and exact offsets.
- A table helper can accept original text, the length-preserving mask, provisional/public candidate ranges, and one location callback. That avoids file I/O and avoids inventing a separate position mapping.
- The existing _read_braced_argument uses text.find and is intentionally shallow; table parsing needs its own balanced-group reader for column specs, caption, formatting, and multicolumn while leaving include behavior compatible.
- Existing environment recovery silently adjusts mismatched stacks for candidate context. Table parsing must add explicit unexpected/unclosed table diagnostics without breaking ordinary candidate extraction.

## Test and CLI compatibility

- Existing domain and application tests construct PaperScanStatistics and PaperScanResult positionally. To minimize breakage, new statistics fields should be appended with defaults only if dataclass ordering remains valid; otherwise update all constructors explicitly and treat the schema change as intentional.
- scan_paper --file currently filters candidates only. It must also filter tables by source path and recompute table statistics while leaving graph and diagnostics behavior compatible.
- CLI JSON schema_version is currently "1" and result_type is raw_numeric_candidates. Adding tables is a schema change; Stage 4B1 should move scan JSON to schema_version "2" and a result type that still clearly includes raw candidates, while error JSON stays consistent.
- Default human output must add a compact table reliability summary but retain the raw candidate table and low-context filtering. --show-tables should be orthogonal to --show-all and --file.
- Existing tests strongly assert exact candidate extraction, CRLF ranges, no input mutation, stable JSON, error mapping, and limit monkeypatching. Table work must not perturb these facts.

## Diagnostics and performance

- SourceLocation permits exact full ranges and has stable display formatting. Table/cell diagnostics can reuse make_input_diagnostic with evidence details such as table index, row index, and physical/logical cell index.
- Diagnostic sorting is severity, code, location display, then deterministic ID; table diagnostics should use the same shared sort key.
- Current Stage 4A performance tests compare 1,250 vs 5,000 numeric candidates. Stage 4B1 needs a separate synthetic table workload with dozens of tables and thousands of cells, plus exact candidate identity/count assertions.
- Only four production/test construction sites currently instantiate PaperScanResult/PaperScanStatistics, so an explicit constructor update is manageable and clearer than compatibility defaults if field invariants benefit from required values.

## Implemented domain decisions

- LatexTable represents each actual tabular/tabular* structure; an optional table/table* container is attached rather than emitted as a separate data table.
- Recognized unsupported longtable/tabularx/array structures can be emitted with UNSUPPORTED reliability and no fabricated rows.
- LatexCellNumericReference holds the existing RawNumericCandidate object directly and stores sorted formatting kinds for its primary numeric value.
- LatexTableCell retains whole-cell and effective-content ranges, logical start/span, raw multicolumn format, exact formatting spans, normalized text, limitations, and reliability.
- PaperScanStatistics partitions table_count exactly into parsed, degraded, and unsupported counts.
## Verified implementation findings

- A dedicated adapters/latex_tables.py keeps table parsing out of the Stage 4A lexer while consuming only cached original text, the length-preserving mask, existing candidates, and the existing line-map callback.
- Basic table parsing supports table/table* ownership, tabular/tabular*, caption/label before or after tabular, multiple tabulars per container, standalone tabulars, CRLF, and include files.
- The row state machine handles top-level ampersands, row terminators with optional spacing, tabularnewline, escaped ampersands, brace groups, math, nested environments, comments/code masks, empty cells, and final unterminated rows.
- Column counting covers basic l/c/r/p/m/b, vertical rules, decorations, and bounded literal repeat specs. Unknown types are preserved with unavailable expected count.
- Candidate-specific formatting correctly distinguishes multiple values in one cell and nested textbf/underline; unsupported formatting is not misclassified.
- One Stage 4A defect was found and fixed: a number directly before a TeX command such as 89.0 followed by end was misclassified as a filename token. Backslash now terminates the URL/filename heuristic, with table formatting coverage exercising the regression.
- Scan JSON is schema version 2 with result_type paper_scan. It contains table/cell ranges, structure, candidate references, and formatting without Rich objects.
- The generated workload verifies 50 tables, 1,000 rows, 5,000 cells, and direct reuse of all 5,000 table candidate objects; the test completed in about 0.60 seconds on the verification machine.
- Final automated evidence is 220 passed, 2 skipped, 90.07% coverage; Ruff, formatting, Pyright strict, compileall, build, CLI, and acceptance verification pass.
