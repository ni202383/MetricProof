# Claim candidate classification

Stage 4B2a classifies each existing `RawNumericCandidate` with deterministic,
reviewable heuristics. It does not create a persistent Claim, Claim ID,
fingerprint, link, `claims.yml` record, or rule diagnostic.

## Result model

Each `ClaimCandidateClassification` contains:

- the existing raw candidate reference;
- `ClaimDisposition`;
- `ClaimKind`;
- an integer score from 0 to 100;
- `ClaimConfidence`;
- whether it belongs in the default future review queue;
- ordered positive, negative, or neutral evidence.

`ClaimDisposition` values:

- `likely_experiment_claim`: strong explainable evidence; recommended for the
  default future linking review.
- `possible_experiment_claim`: plausibly experimental but requires human
  judgment.
- `ambiguous`: insufficient or conflicting evidence.
- `non_experiment`: explicit structural evidence indicates that the number is
  not an experimental Claim candidate.

`ClaimKind` values:

- `direct_result`
- `derived_result`
- `summary_statistic`
- `experiment_quantity`
- `unknown`

`ClaimConfidence` is `high`, `medium`, or `low`. It is evidence strength, not a
calibrated probability.

## Central score and thresholds

Classification starts at 30 and clamps the final score to 0–100.

Representative positive contributions:

| Evidence | Impact |
|---|---:|
| bounded metric context | +40 |
| bounded comparison language | +20 |
| local derived expression | +20 |
| experiment quantity context | +15 |
| parsed numeric-like table cell | +20 |
| degraded numeric-like table cell | +8 |
| parsed/degraded table metric context | +30 / +18 |
| compound mean ± std | +15 |
| bold or underline | +5 |
| percentage | +5 |
| decimal or scientific notation | +3 |

Representative negative contributions:

| Evidence | Impact |
|---|---:|
| cite/ref/label/bibitem argument | -100 |
| layout or sizing command argument | -90 |
| section/chapter structure argument | -80 |
| explicit layout dimension | -80 |
| document number | -70 |
| URL/DOI/arXiv identifier | -80 |
| contextual version/date/year | -65 to -70 |
| color or coordinate context | -70 |
| text-like first table column | -25 |
| generic command argument | -20 |
| unsupported table structure | -8 |
| generic math constant | -10 |

Hard structural exclusions produce `non_experiment`. Strong positive and
negative evidence in conflict produces `ambiguous`. Otherwise:

- score at least 70: `likely_experiment_claim`;
- score at least 45: `possible_experiment_claim`;
- score at most 20 with negative evidence: `non_experiment`;
- remaining cases: `ambiguous`.

`experiment_quantity` values are capped semantically at possible or ambiguous;
they are not promoted to likely performance results solely because they are
experiment-related.

## Bounded processing

- Text rules inspect only the scanner's existing finite prefix/suffix context.
- Metric aliases extend a small built-in vocabulary through strict
  `metric_aliases` configuration.
- Table facts come only from `PaperScanResult.tables`.
- Candidate-to-table context is indexed once; the classifier does not traverse
  all tables for every candidate.
- Parsed, degraded, and unsupported tables contribute different evidence.
- Mean ± std remains one compound candidate and is never recomputed.
- The classifier does not read files, parse LaTeX again, read experiment
  results, execute TeX, or access the network.

## CLI and JSON

`metricproof scan` includes classification counts in its summary.

- `--show-claims` shows likely and possible review candidates.
- `--show-all` shows every classification and retains raw debug detail.
- `--show-tables` retains the Stage 4B1 structural table view.
- `--json` emits paper scan schema version 3.

Schema version 3 retains raw candidates and table facts and adds
`claim_classifications`. Each classification uses a deterministic zero-based
`candidate_index` into the current scan's `candidates` array. This is a
scan-local reference, not a stable Claim ID.

## Limitations

These rules deliberately favor explainability and lower obvious false-positive
rates over complete paper understanding. `likely_experiment_claim` does not mean
that a paper conclusion is confirmed. `non_experiment` can still be wrong in
unusual notation. Every result remains available for human review. Stage 5 identity/link/check services consume
likely and possible results, but classification alone never confirms a link or emits a rule finding.

