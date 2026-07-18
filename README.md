# MetricProof

MetricProof is an open-source, local-first Python CLI for checking research artifacts with deterministic, explainable rules.

The Stage 5 local MVP is implemented. MetricProof strictly loads
`.metricproof/config.yml`, reads declared JSON/YAML/CSV results, scans controlled
LaTeX sources, classifies numeric Claims, assigns stable versioned identities, and
supports user-confirmed links in `.metricproof/claims.yml`. `metricproof check`
produces the same deterministic `CheckResult` as terminal or versioned JSON for
`STALE_VALUE`, `WRONG_DELTA`, and `MISSING_PROVENANCE`.

Diagnostics are representation-consistency findings and heuristic risks. They do
not decide whether a paper, experiment, or scientific conclusion is correct.

## Requirements

- Python 3.13 or newer, below Python 4.0
- No network service, database, AI API, or experiment platform is required
- Git is optional for `doctor`; unavailable Git is reported as an environment failure

## Shortest scan → link → check workflow

From a configured project root:

```text
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
metricproof link
metricproof check
metricproof check --json
```

The non-interactive link command is read-only: it emits ranked candidates and
feature contributions but never confirms or writes a link. Run interactive
`metricproof link` to select a direct metric, choose a bounded derived operation,
or record an explicit ignore decision. Confirmed decisions are validated and
written atomically once to `.metricproof/claims.yml`; cancelling leaves the old
file unchanged.

`metricproof check` reloads the current paper, experiment catalog, and registry,
migrates retained Claim identities when it can do so uniquely, and then runs the
three MVP rules. Use `--rule CODE` to select one rule and `--fail-on warning|error`
to control only rule-finding exit status. Configuration and input/link errors are
never hidden by `--fail-on`.

## Development setup

Create and activate a virtual environment:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
```

On Linux or macOS, activate it with `source .venv/bin/activate`.

Install the project in editable mode with development dependencies:

```text
python -m pip install -e ".[dev]"
```

If the environment is intentionally offline and build dependencies are already installed:

```text
python -m pip install --no-build-isolation -e ".[dev]"
```

## Minimal experiment configuration

Create `.metricproof/config.yml` in the project root. This single-run JSON example only reads the explicitly declared metric and metadata selectors:

```yaml
schema_version: "1"
result_paths:
  - path: runs/baseline.json
    format: json
    run_id: baseline
    structured:
      metrics:
        accuracy: metrics.accuracy
      metadata:
        dataset: context.dataset
        split: context.split
        seed: context.seed
```

`runs/baseline.json`:

```json
{
  "metrics": {"accuracy": 0.872},
  "context": {"dataset": "cifar10", "split": "test", "seed": 7}
}
```

JSON and YAML can also read an explicit array of run mappings. Arrays are never auto-expanded as metrics:

```yaml
schema_version: "1"
result_paths:
  - path: runs/results.yml
    format: yaml
    structured:
      records_selector: runs
      run_id_selector: id
      metrics:
        accuracy: metrics.accuracy
      metadata:
        dataset: dataset
```

`runs/results.yml`:

```yaml
runs:
  - id: baseline
    dataset: cifar10
    metrics:
      accuracy: 0.841
  - id: proposed
    dataset: cifar10
    metrics:
      accuracy: 0.872
```

CSV is intentionally explicit and uses the Python standard library, not pandas:

```yaml
schema_version: "1"
result_paths:
  - path: runs/seeds.csv
    format: csv
    csv:
      run_id_column: run_id
      metric_columns: [accuracy, loss]
      metadata_columns: [dataset, split, seed]
```

`runs/seeds.csv`:

```csv
run_id,accuracy,loss,dataset,split,seed
seed-1,0.871,0.42,cifar10,test,1
seed-2,0.873,0.40,cifar10,test,2
```

Optional `config_reference` on a result source preserves one project-relative experiment configuration file. `experiment_config_paths` validates and records additional JSON/YAML configuration files for later stages; Stage 3 does not compare them or judge experimental fairness.

All paths and globs are project-relative. Absolute paths, `..` traversal, missing files, duplicate path aliases, and symlink escapes are rejected.

## Minimal LaTeX scan configuration

Declare one or more exact `.tex` entry paths. Unlike result sources, `paper_paths`
does not accept globs:

```yaml
schema_version: "1"
paper_paths:
  - paper/main.tex
exclude_paths:
  - build/**
```

`metricproof scan` follows static relative `\input{}` and `\include{}`
dependencies, including omitted `.tex` suffixes. Each physical file is scanned
once while candidate provenance retains every configured entry that reaches it.
Comments, `\verb`, `verbatim`, `Verbatim`, `lstlisting`, and `minted` content are
excluded. Basic tables reuse the same already-read source, mask, exact locations,
and `RawNumericCandidate` objects. Cell separators are unescaped top-level `&`;
row separators are top-level `\\` or `\tabularnewline`. Separators inside groups,
math, nested environments, comments, and excluded code do not split cells.

Supported structure facts include caption/label ownership, basic `l`/`c`/`r` and
`p`/`m`/`b` column specifications, `@{...}` decorations, basic
`\multicolumn{N}{FORMAT}{CONTENT}`, booktabs/hline markers, and candidate-specific
`\textbf{...}` / `\underline{...}` spans. `multirow` is retained with an explicit
degraded limitation. `longtable`, `tabularx`, `array`, `matrix`, and `aligned` are recognized as
unsupported rather than misparsed as ordinary tabular structures.

## CLI

```text
metricproof --help
metricproof --version
metricproof doctor
metricproof scan
metricproof scan --json
metricproof scan --show-claims
metricproof scan --show-all
metricproof scan --show-tables
metricproof scan --file paper/section.tex
metricproof experiments --help
metricproof experiments list
metricproof experiments list --json
metricproof experiments validate
metricproof experiments validate --json
python -m metricproof experiments --help
metricproof link
metricproof link --claim CLAIM_ID
metricproof link --non-interactive --json
metricproof link --show-broken
metricproof check
metricproof check --json
metricproof check --rule STALE_VALUE
metricproof check --fail-on warning
python -m metricproof link --help
python -m metricproof check --help
```

- `experiments list` displays normalized runs, metrics, source files, and selectors.
- `experiments validate` validates config and every source without modifying them.
- `scan` displays raw candidate, Claim-disposition, table, and diagnostic counts.
  Classifications are reviewable heuristics, not confirmed paper conclusions.
- `scan --show-claims` displays likely and possible review candidates with kind,
  score, confidence, and key positive/negative evidence.
- `scan --show-all` displays every classification and all raw debug contexts.
- `scan --show-tables` expands table metadata, rows, short cell content, numeric
  references, formatting, reliability, and limitation codes.
- `scan --file` filters candidates and tables to a file already present in the
  configured dependency graph; it cannot read an arbitrary path.
- `scan --json` writes schema version `3` with all raw candidates, exact table/cell
  facts, and `claim_classifications` linked by a scan-local `candidate_index`.
  The index is not a persistent Claim ID.
- Invalid project configuration or file selection exits with code `2`; blocking
  input diagnostics exit with code `3`.

## Safety and supported boundaries

- YAML uses a safe loader and rejects duplicate keys, unsafe tags, and multiple documents.
- JSON rejects duplicate object keys and non-finite constants.
- JSON/YAML numbers are converted from lexical text to `Decimal` without a binary `float` round trip.
- CSV values are converted directly from source strings and support standard quoting/newlines.
- Booleans, empty strings, `NaN`, and infinities are not valid metric values.
- Built-in limits are 5,000,000 bytes per file, nesting depth 64, 1,000 result sources, and 100,000 CSV rows.
- MetricProof does not execute result files, TeX, Python modules, training scripts, or expressions.
- LaTeX limits are 5,000,000 bytes per file, 25,000,000 total bytes, 1,000 files,
  include depth 32, environment depth 128, and 100,000 numeric candidates.
- Table limits are 1,000 tables, 10,000 rows per table, 1,000 physical cells per
  row, 100,000 cells per table, 100,000 characters per cell, nesting depth 16,
  and multicolumn span 1,000.
- Dynamic macro expansion, external code inclusion, full TeX interpretation,
  complex cross-row structures, and header/best-value semantics are unsupported.

## Claim registry and MVP rules

`.metricproof/claims.yml` is a schema-versioned, human-readable record of confirmed
Claim-to-metric links and explicit ignore decisions. It stores stable identity
snapshots and migration evidence, not a copy of all experiment results. Unknown
fields, duplicate IDs, incompatible schemas, unsafe YAML, invalid links, absolute
paths, and path escapes are rejected. Writes use a same-directory temporary file,
flush/fsync, and atomic replacement; `scan` never modifies the registry.

The implemented rules are:

- `STALE_VALUE`: compares an active `DirectLink` with the current observation using
  exact `Decimal`, explicit scale, configured tolerance, and the paper's display-
  precision interval.
- `WRONG_DELTA`: recomputes a confirmed one-layer `DerivedLink` using subtraction,
  relative change, mean, or explicitly sample/population standard deviation.
- `MISSING_PROVENANCE`: reports a currently locatable likely experimental Claim
  that has neither an active link nor an IgnoreRecord. Possible Claims are included
  only when configured.

A fraction such as `0.872` and a displayed percentage such as `87.2\%` normalize to
the same canonical proportion. A percentage-point subtraction is different from a
relative percentage change: `0.90 - 0.70` is `20.0` percentage points, while the
relative change is about `28.57%`. Link scale and derived output unit are explicit;
MetricProof never silently persists a guess.

## Local MVP demo

The fully fictional project in `examples/mvp-demo` is checked in with a strict
configuration and registry:

```text
cd examples/mvp-demo
metricproof experiments validate
metricproof scan --show-claims
metricproof link --non-interactive --json
metricproof check
metricproof check --json
```

`check` intentionally exits `1`: it reports one stale percentage (`80.0%` linked
to `0.90`), one wrong displayed delta (`25.0` versus `20.0` percentage points), and
one missing provenance warning. The baseline `70.0%` and F1 `0.750` links remain
quiet, while the `10.0`-second run setting is explicitly ignored. See
[`docs/linking-and-checking.md`](docs/linking-and-checking.md) for the workflow and
exit-code contract.
## Quality checks

```text
python -m pytest
python -m pytest --cov=metricproof --cov-report=term-missing
python -m ruff check .
python -m ruff format --check .
pyright
python -m build
```

For an intentionally offline environment with local build dependencies available, use `python -m build --no-isolation`.

## Current limitations

- `WRONG_BEST_MARK` and `UNFAIR_COMPARISON` are not implemented.
- Table header/direction/best-value interpretation is not implemented.
- HTML reports, Git evidence, GitHub Actions, SARIF, PDF/Word, Overleaf, remote
  services, databases, Web UI, plugins, AI/LLM integrations, and automatic paper
  fixes are not implemented.
- Only controlled LaTeX source, JSON/YAML/CSV results, and local read-only Git
  inspection are in scope. MetricProof does not execute TeX, training code, user
  scripts, or arbitrary expressions.
- Highly repeated or substantially rewritten Claim context can require manual
  relinking. Ambiguous migration is intentionally refused.
