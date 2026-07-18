# Linking, checking, and reporting

MetricProof turns scanned numeric Claim candidates into explicit, reviewable provenance decisions. Candidate matching is advisory; only an interactive user confirmation creates or changes a link.

## 1. Prepare and inspect

```text
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
```

`scan --show-claims` presents likely and possible experimental Claims with heuristic evidence. Non-interactive `link` adds stable Claim IDs, migration status, ranked candidates, score contributions, suggested scale/type, and uncertainties. It never prompts or writes `.metricproof/claims.yml`.

Matching is bounded and deterministic: Decimal value/display precision, explicit fraction/percent conversions, metric names and configured aliases, nearby run/dataset/split text, Claim kind, and clear derived wording. Equal or near-equal candidates remain ambiguous. A matching value is evidence, not confirmation.

## 2. Confirm links or ignores

```text
metricproof link
metricproof link --claim clm_0123456789abcdef0123
metricproof link --show-broken
```

Interactive review can select a direct candidate and scale, choose a loaded run/metric manually, confirm a bounded derived operation, skip, persist an IgnoreRecord, or review a broken link. Active links require separate overwrite confirmation. Decisions are aggregated in memory and the strict schema-versioned registry is atomically replaced once. Cancel, Ctrl+C, no decisions, and failures preserve the old file.

Derived links allow one controlled subtraction, relative change, mean, or sample/population standard deviation. They do not accept arbitrary expressions, functions, scripts, or recursive formulas.

## 3. Configure table and comparison checks

`WRONG_BEST_MARK` runs only for a declared `table_checks` entry. The declaration identifies a LaTeX table label, row range, label column, metric columns, higher/lower directions, tie tolerance, and required best/optional second-best formatting. The rule does not infer these semantics from prose or headers. Missing cells are skipped; degraded, unsupported, ambiguous, or unknown-macro structures produce limitations rather than guessed conclusions.

`UNFAIR_COMPARISON` runs only for declared comparisons. Each comparison names baseline/candidate run IDs and `controlled_keys`; each run must carry a project-relative JSON/YAML `config_reference`. MetricProof loads only the requested keys. An allowed difference must name the key and preserve a non-empty user reason. Exact type/value comparison is the default; numeric tolerances are explicit Decimal values.

## 4. Run checks

```text
metricproof check
metricproof check --json
metricproof check --rule STALE_VALUE
metricproof check --rule WRONG_DELTA
metricproof check --rule MISSING_PROVENANCE
metricproof check --rule WRONG_BEST_MARK
metricproof check --rule UNFAIR_COMPARISON
metricproof check --fail-on warning
```

One scan, one experiment catalog, one link session, and the minimal declared config snapshots feed one schema-versioned `CheckResult`. Five pure rules run over these prepared domain objects:

- `STALE_VALUE`: linked displayed value differs from its observation after explicit scale, display precision, and tolerance.
- `WRONG_DELTA`: linked derived value differs from recomputation under a controlled operation/unit/rounding policy.
- `MISSING_PROVENANCE`: a locatable experimental Claim has neither an active link nor an explicit ignore decision.
- `WRONG_BEST_MARK`: a configured table cell's bold/underline state differs from the computed tied best/second-best set.
- `UNFAIR_COMPARISON`: a declared controlled config key differs without a documented allowed-difference reason.

Broken sources and non-unique migration create input/link diagnostics and suppress misleading dependent findings. Ignored Claims do not produce missing provenance. A rule name such as `UNFAIR_COMPARISON` is a review label, never a verdict that an experiment is invalid or scientifically unfair.

## 5. Render reports

```text
metricproof report --format html --output reports/metricproof.html --no-timestamp
metricproof report --format json --output reports/metricproof.json --no-timestamp
```

Terminal, JSON, and HTML render the same `CheckResult`; renderers do not apply rule logic. The single-file HTML has inline CSS, no JavaScript, no external resources, and escaped project-controlled text. Output must remain within the project and is written atomically. A valid report is written before rule-threshold exit code `1` is returned. See [html-report.md](html-report.md).

## 6. Numeric semantics

A displayed `87.2\%` has canonical proportion `0.872` and one-decimal display interval `[0.8715, 0.8725)`. Direct scales are explicit: `identity`, `fraction_to_percent`, or `percent_to_fraction`.

```text
subtraction:      candidate - baseline
relative_change: (candidate - baseline) / abs(baseline)
percent_points:   (candidate - baseline) * 100
```

For baseline `0.70` and candidate `0.90`, the scalar difference is `0.20`, percentage-point difference is `20.0`, and relative change is about `28.57%`. MetricProof never interchanges them.

## 7. Exit codes

| Code | Meaning |
|---:|---|
| `0` | Completed below the configured rule threshold |
| `1` | Analysis/report completed and rule findings reached the threshold |
| `2` | Invalid CLI usage or project configuration |
| `3` | Blocking input, parse, registry, or link-integrity problem |
| `4` | Environment/read-only tool failure |
| `5` | Unexpected internal failure |
| `130` | User interruption |

`--fail-on` affects rule findings only. It does not hide configuration/input errors. `--no-timestamp` JSON and HTML are byte-stable for identical inputs.

## 8. Checked-in Demo

```text
cd examples/mvp-demo
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
metricproof check
metricproof report --format html --output metricproof-report.html --no-timestamp
```

The fictional Demo intentionally returns `1`, with findings from all five rules and quiet negative cases. The command sequence does not modify paper, results, configurations, or registry. The README visual is generated from the same real Demo CheckResult.

Current scope excludes Git evidence chains, GitHub Actions, SARIF, PDF/Word/Overleaf, remote services, Web UI, databases, plugins, and network/AI services.