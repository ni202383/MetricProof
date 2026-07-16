# MetricProof Stage 4B1 Implementation Plan

## Goal

Implement deterministic, traceable, resource-bounded LaTeX table structure parsing on Python 3.13 and the stable Stage 4A scan interfaces. Reuse existing source text, positions, diagnostics, and RawNumericCandidate objects while adding rows, cells, column specifications, caption/label ownership, structure markers, basic multicolumn, explicit multirow degradation, and candidate-specific textbf/underline formatting.

## Current phase

Phase 8 complete: completion audit passed.

## Phases and gates

| Phase | Status | Gate |
|---|---|---|
| 1. Documents, code, and pre-change baseline | complete | Read required docs and scanner/domain/tests; verify Git/Python; pytest, coverage, Ruff, format, Pyright, and build pass |
| 2. Domain models, ports, and resource limits | complete | Minimal immutable table models, statistics, and centralized limits preserve architecture and exclude Claim semantics |
| 3. Table boundaries, column specs, and row/cell state machine | complete | Supported environments, top-level separators, structure commands, caption/label, stable ranges, and controlled recovery work |
| 4. Cell semantic associations | complete | Existing candidates are reused; basic multicolumn, multirow degradation, and candidate-specific formatting work |
| 5. Application result and CLI/JSON | complete | PaperScanResult/statistics, default summary, --show-tables, versioned JSON, and exit codes work |
| 6. Tests, performance, and defect repair | complete | Positive, negative, boundary, resource, and regression tests pass; thousands of cells avoid obvious quadratic behavior |
| 7. Documentation, acceptance project, and full verification | complete | Direct docs are synchronized and every required command and acceptance scenario is recorded |
| 8. Completion audit | complete | All 15 completion criteria pass without Claim/rule/network/remote/destructive scope expansion |

## Constraints

- Preserve CLI -> application -> domain; adapters implement application ports.
- Domain must not depend on Typer, Rich, pylatexenc, or the file system, and must not retain parser nodes.
- Do not create duplicate SourceLocation, RawNumericCandidate, or InputDiagnostic types.
- Do not reread files into a second coordinate system or recreate numeric candidates.
- Do not execute TeX, macros, user scripts, or expressions; never use eval, exec, or shell=True.
- Do not implement headers, metric names, optimization direction, best/second-best, PaperClaim, Claim IDs, experiment links, or paper rules.
- No network, commit, push, remote resources, or release actions.

## Initial facts

- The worktree was clean at start on main...origin/main.
- Stage 4A completed with 186 passed, 2 skipped, and 90.82% branch coverage; Ruff, formatting, Pyright, compileall, build, CLI, and acceptance projects passed.
- Root historical planning files remain unchanged; this stage uses .planning/stage4b1/.

## Errors

| Error | Attempt | Resolution |
|---|---:|---|
| PowerShell displayed the UTF-8 goal attachment as mojibake | 1 | Re-read explicitly as UTF-8 with Python |
| An active preliminary goal only represented reading the attachment | 1 | Completed it and created the real Stage 4B1 goal |
| apply_patch was rejected by the Windows restricted-token sandbox | 1 | Use the repository-established exact unified diff fallback with dry-run |
| Handwritten fallback hunk counts were wrong | 1 | Use git apply --recount |
| Strict whitespace check rejected EOF/CRLF details | 1 | Use whitespace warnings for planning Markdown and verify the resulting diff |
| PowerShell converted non-ASCII patch content to question marks | 1 | Replace only newly created planning files with ASCII records; keep product edits patch-based |

