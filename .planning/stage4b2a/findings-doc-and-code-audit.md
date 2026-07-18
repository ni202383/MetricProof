# Stage 4B2a document and initial code audit

## Document conclusions

- `SPEC.md` and `ARCHITECTURE.md` stop current scan behavior at Stage 4B1 and
  place Claim classification immediately after `PaperScanResult`.
- `PaperScanResult.tables` is the only allowed source of table structure facts
  for Stage 4B2a.
- Existing documents describe future persistent `PaperClaim`,
  `ClaimFingerprint`, links, and checks. Stage 4B2a needs a distinct
  non-persistent classification result rather than partially instantiating
  those future models.
- The future `ClaimKind` and `ClaimClassification` names in
  `docs/data-model.md` do not match the Stage 4B2a objective semantics. Naming
  must be made unambiguous with a minimal documentation adjustment.
- Confidence is already specified as deterministic evidence strength, not a
  calibrated probability.
- Future `MISSING_PROVENANCE` semantics confirm uncertain candidates are review
  inputs rather than default rule diagnostics; that rule remains out of scope.
- The recorded Stage 4B1 baseline is 220 passed, 2 skipped, 90.07% coverage,
  with lint, format, Pyright, compile, and build passing. It must be rerun.

## Initial implementation conclusions

- `RawNumericCandidate` is an immutable dataclass with exact source location,
  limited prefix/suffix, command, environment stack, entry provenance, and an
  optional uncertainty for compound mean/std candidates.
- `PaperScanResult` is immutable, already contains stable candidate ordering
  from the scanner and stable table ordering, and exposes blocking scan errors.
- Table cells reference the same `RawNumericCandidate` object through
  `LatexCellNumericReference`; classification can build a one-pass
  candidate-to-table-context index without copying or rescanning candidates.
- `LatexTableReliability` already provides the exact parsed/degraded/unsupported
  distinction needed for evidence weights.
- `scan_paper` is the existing application orchestration boundary and supports
  graph-file filtering without rereading disk.
- The CLI currently owns human and JSON rendering for schema 2. Stage 4B2a can
  reuse this composition point, but the classifier itself must remain outside
  the CLI and concrete adapter.
- Existing tests use frozen domain fixtures, fake scanner ports, Typer
  `CliRunner`, stable JSON equality, project immutability snapshots, and
  table-reference identity checks. New tests should follow these patterns.

## Tooling constraint

- `apply_patch` can add new files, but every attempted read-modify update of an
  existing file fails before execution because the Windows restricted-token
  patch wrapper cannot enforce the configured split writable roots.
- This is an environment/tooling failure, not a repository defect. Existing
  file updates will require a reviewed unified-diff fallback unless the wrapper
  begins working later.

