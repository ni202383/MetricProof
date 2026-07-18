# Stage 4B2a LaTeX implementation audit

- The scanner already records only bounded source context via `prefix` and
  `suffix`; classification can match lexical evidence on these finite strings
  rather than rescanning entire documents.
- Existing `command`, `environments`, and `LatexSyntacticContext` fields provide
  the first structural negative-evidence layer for command arguments, captions,
  math, and tables.
- The scanner already suppresses obvious URL/file/version/hex forms at lexical
  extraction time. Stage 4B2a still needs conservative contextual reasons for
  candidates that survive lexical filtering, but must not duplicate the entire
  scanner.
- Table parsing already builds a candidate index and associates candidates with
  exact cells. The classifier should build one table-context lookup once per
  `PaperScanResult`, not traverse all tables for each candidate.
- `normalized_text` is available for captions, labels, and cells, so metric and
  experiment-quantity terms can be matched on bounded structural text without
  executing TeX or preserving parser objects.
- Formatting is candidate-specific through each numeric reference, enabling
  weak bold/underline evidence without treating the whole cell as formatted.
- Existing tests cover compound mean/std, command contexts, table reliability,
  nested formatting, identity reuse, and resource limits. Stage 4B2a tests
  should exercise classification semantics rather than duplicate parser-state
  coverage.

