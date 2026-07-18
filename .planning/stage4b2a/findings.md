# MetricProof Stage 4B2a Findings

## Initial facts

- The attached objective defines deterministic, explainable classification of
  existing LaTeX raw numeric candidates.
- The initial worktree is clean on `main...origin/main`.
- Prior Stage 4A and Stage 4B1 scoped plans are preserved.
- The objective requires a strict pre-change quality gate.

## Required audit targets

- `AGENTS.md`, `SPEC.md`, `ARCHITECTURE.md`
- `docs/data-model.md`, `docs/rule-semantics.md`, `docs/status.md`
- Current paper, LaTeX, and LaTeX-table implementations and related tests
- Git state, Python 3.13, pytest, coverage, Ruff, format, Pyright, and build

## Design constraints

- Every raw candidate gets one result containing disposition, kind,
  deterministic score, confidence level, and evidence.
- Strong structural negative evidence can override weak lexical positives.
- Parsed, degraded, and unsupported tables have different evidence strength.
- Mean ± std stays one compound classification unit.
- Experiment quantities remain possible or ambiguous unless stronger evidence
  supports a reported result.
- Stable identity and formal relationships are deferred.

