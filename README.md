# MetricProof

MetricProof is an open-source, local-first Python CLI for checking research artifacts with deterministic, explainable rules.

Stage 4A is implemented: MetricProof can strictly load `.metricproof/config.yml`,
read declared JSON, YAML, and CSV experiment results, and scan a controlled LaTeX
source graph for exact `Decimal`-based raw numeric candidates. Claim semantics,
table interpretation, linking, the five paper consistency rules, and formal HTML
reports are not implemented yet.

## Requirements

- Python 3.13 or newer, below Python 4.0
- No network service, database, AI API, or experiment platform is required
- Git is optional for `doctor`; unavailable Git is reported as an environment failure

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
excluded.

## CLI

```text
metricproof --help
metricproof --version
metricproof doctor
metricproof scan
metricproof scan --json
metricproof scan --show-all
metricproof scan --file paper/section.tex
metricproof experiments --help
metricproof experiments list
metricproof experiments list --json
metricproof experiments validate
metricproof experiments validate --json
python -m metricproof experiments --help
```

- `experiments list` displays normalized runs, metrics, source files, and selectors.
- `experiments validate` validates config and every source without modifying them.
- `scan` displays raw numeric candidates and source positions from the configured
  LaTeX graph. It does not classify them as paper claims.
- `scan --show-all` also displays low-context command-argument and unknown candidates.
- `scan --file` filters to a file already present in the configured dependency graph;
  it cannot read an arbitrary path.
- `--json` writes one stable JSON document to stdout without Rich formatting.
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
- Dynamic macro expansion, external code inclusion, full TeX interpretation, and
  table row/column semantics are intentionally unsupported.

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

## Not implemented yet

- Paper Claim discovery, IDs, linking, migration, or `claims.yml`
- Table row/column/header semantics and best-value interpretation
- `STALE_VALUE`, `WRONG_DELTA`, `MISSING_PROVENANCE`, `WRONG_BEST_MARK`, or `UNFAIR_COMPARISON`
- Formal `check`, versioned check-result JSON, or HTML reports
- GitHub Actions, remote services, databases, plugins, or AI integrations
