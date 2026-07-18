# Stage 4B2a classification design decision

## Domain result

- `ClaimDisposition`: likely experiment claim, possible experiment claim,
  ambiguous, or non-experiment.
- `ClaimKind`: direct result, derived result, summary statistic, experiment
  quantity, or unknown.
- `ClaimConfidence`: high, medium, or low.
- `ClaimEvidence`: stable reason code, direction, integer score impact,
  explanation, source location, and bounded structural context.
- `ClaimCandidateClassification`: direct reference to one existing
  `RawNumericCandidate`, disposition, kind, clamped integer score, confidence,
  review recommendation, and ordered evidence.
- `ClaimClassificationResult`: stable classifications, counts, and non-blocking
  diagnostics.

No persistent ID, fingerprint, link, registry, rule diagnostic, or derived
relationship is created.

## Central scoring

- Start from a neutral review score.
- Add explicit bounded lexical/structural evidence for metrics, comparison
  language, parsed/degraded numeric table cells, candidate-specific formatting,
  compound mean/std, and weak numeric shape.
- Add experiment-quantity evidence and classify those values as
  `EXPERIMENT_QUANTITY`, normally possible or ambiguous.
- Apply strong negative evidence for cite/ref/label/bibitem, layout and sizing
  arguments, explicit document numbering, URL/DOI/arXiv/version/date context,
  and color/coordinate context.
- Generic command arguments and math constants receive conservative negative or
  neutral evidence rather than automatic hard exclusion.
- Hard structural exclusions produce `NON_EXPERIMENT`.
- Conflicting strong positive and negative evidence produces `AMBIGUOUS`.
- Thresholds, clamping, confidence levels, and disposition mapping live in one
  domain module.

## Bounded processing

- Text matching uses only each candidate's existing bounded prefix/suffix and
  table normalized text.
- Build metric and quantity vocabularies once per classification call.
- Build a candidate-to-table context index in linear passes over tables/cells.
- Classify the stable candidate set once and sort by existing source key.
- Do not read disk, parse LaTeX, scan experiment results, mutate
  `PaperScanResult`, or traverse all tables for each candidate.

## Configuration

- Reuse the existing strict `metric_aliases` YAML field.
- Preserve normalized aliases in adapter-neutral `ProjectConfiguration`.
- Aliases only extend the small built-in metric vocabulary.
- Scores and thresholds remain code-owned; no custom Python, expressions,
  plugin discovery, or user-adjustable weight matrix.

## CLI and JSON

- Default `scan` summary includes all classification counts.
- `--show-claims` displays likely and possible classifications with key
  evidence.
- `--show-all` displays all classifications and retains raw candidate debug
  detail.
- `--show-tables` remains available.
- JSON advances from schema 2 to schema 3, retains all raw candidates and table
  facts, and adds stable classification objects that reference candidates by
  this scan's deterministic zero-based candidate index.
- The scan-local index is explicitly not a persistent Claim ID.

