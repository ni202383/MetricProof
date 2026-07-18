# Linking and checking

MetricProof's local MVP turns scanned numeric Claim candidates into explicit,
reviewable provenance decisions. Candidate matching is advisory; only an
interactive user confirmation creates or changes a link.

## 1. Prepare and inspect

Run these commands from a project containing `.metricproof/config.yml`:

```text
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
```

`scan --show-claims` shows likely and possible experimental Claims with heuristic
evidence. `link --non-interactive --json` adds stable Claim IDs, migration status,
ranked candidates, score contributions, suggested scale/type, and uncertainties.
It never prompts and never writes `.metricproof/claims.yml`.

Matching uses bounded, deterministic evidence: Decimal value/display precision,
explicit fraction/percent conversions, metric names and configured aliases,
nearby run/dataset/split text, Claim kind, and clear derived wording. Equal or
near-equal candidates remain ambiguous. A matching value is evidence, not an
automatic confirmation.

## 2. Confirm links or ignores

```text
metricproof link
metricproof link --claim clm_0123456789abcdef0123
metricproof link --show-broken
```

The interactive command can:

- select a ranked direct candidate and confirm its explicit scale;
- manually select a loaded run and metric when ranking is insufficient;
- confirm a bounded derived candidate;
- skip a Claim for the current session;
- persist an IgnoreRecord after review;
- review a broken link when `--show-broken` is present.

Active links are not overwritten without a separate confirmation. Decisions are
aggregated in memory and the validated registry is atomically replaced once.
Cancel, Ctrl+C, no decisions, and failures preserve the previous file.

`.metricproof/claims.yml` has schema version `1`. Each sorted entry stores a full
identity snapshot and exactly one link or ignore decision. Direct links retain one
metric reference. Derived links retain only one controlled operation—subtraction,
relative change, mean, or standard deviation—plus named operands, output unit,
scale, rounding, and explicit sample/population mode where applicable. Arbitrary
expressions, functions, scripts, and recursive formulas are rejected.

## 3. Run checks

```text
metricproof check
metricproof check --json
metricproof check --rule STALE_VALUE
metricproof check --rule WRONG_DELTA
metricproof check --rule MISSING_PROVENANCE
metricproof check --fail-on warning
metricproof check --fail-on error
```

One scan and one loaded experiment catalog feed one `LinkSession` and one stable
`CheckResult`. Terminal and JSON render that same result; neither renderer applies
rule logic. Diagnostics are sorted deterministically and include code, severity,
Claim ID, location, observed/expected values, confidence, evidence, related
sources, uncertainties, and remediation.

The three implemented rules are:

- `STALE_VALUE` (error): an active DirectLink's current observation falls outside
  the Claim's half-open display-precision interval after explicit scale and
  absolute/relative tolerance.
- `WRONG_DELTA` (error): the displayed derived Claim differs from a recomputed
  bounded operation after explicit unit adjustment, scale, and rounding.
- `MISSING_PROVENANCE` (warning by default): a currently locatable likely Claim
  has neither an active link nor an explicit ignore. Possible Claims are excluded
  unless `policy.include_possible_missing_provenance` is true.

Broken sources or non-unique Claim migration produce link/input diagnostics and
suppress misleading numeric rule findings. Ignored Claims do not produce missing
provenance. These are representation-consistency diagnostics, not findings about
scientific validity, paper truth, or research integrity.

## 4. Fractions, percentages, and percentage points

Metric values are deterministic `Decimal` values. A displayed `87.2\%` has
canonical proportion `0.872`; its one-decimal display interval is
`[0.8715, 0.8725)`. Direct link scales are explicit `identity`,
`fraction_to_percent`, or `percent_to_fraction` values.

Derived operations also keep their unit explicit:

```text
subtraction:      candidate - baseline
relative_change: (candidate - baseline) / abs(baseline)
percent_points:   (candidate - baseline) * 100
```

For baseline `0.70` and candidate `0.90`, the scalar difference is `0.20`, the
percentage-point difference is `20.0`, and the relative change is approximately
`28.57%`. MetricProof does not interchange these meanings.

## 5. Exit codes and JSON

| Code | Meaning |
|---:|---|
| `0` | Completed without a rule finding at the configured threshold |
| `1` | Analysis completed and a rule finding reached `--fail-on` |
| `2` | Invalid CLI usage or project configuration |
| `3` | Blocking input, parsing, registry, or link-integrity problem |
| `4` | Environment or read-only tool failure |
| `5` | Unexpected internal failure |
| `130` | User interruption |

`--fail-on` affects only rule diagnostics; it never masks configuration or input
errors. JSON stdout is pure, versioned, byte-stable for identical inputs, and
includes the tool version, project/registry/migration summaries, and diagnostics.

## 6. Checked-in demo

```text
cd examples/mvp-demo
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
metricproof check
metricproof check --json
```

The demo intentionally returns exit code `1` from `check`. It contains two quiet
consistent links, one ignored run-setting number, and exactly one finding for each
MVP rule. All data is fictional. The commands read the paper and experiment files
without modifying them.

Current scope does not include `WRONG_BEST_MARK`, `UNFAIR_COMPARISON`, HTML
reports, Git evidence chains, GitHub Actions, SARIF, or any network/AI service.
