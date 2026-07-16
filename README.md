# MetricProof

MetricProof is an open-source, local-first Python CLI for checking whether experimental claims remain consistent with local research artifacts.

The project is in local development. Stage 1 provides only the installable package, quality tooling, base CLI, and non-destructive environment diagnostics. Paper scanning, experiment loading, Claim linking, consistency rules, and formal JSON/HTML reports are not implemented yet.

## Requirements

- Python 3.13 or newer, below Python 4.0
- Git is optional for `doctor`, but unavailable Git is reported as an environment failure

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

## CLI

```text
metricproof --help
metricproof --version
metricproof doctor
python -m metricproof --help
```

`doctor` only reads environment and repository metadata. It does not create configuration, parse LaTeX, execute TeX or user code, or modify Git.

## Quality checks

```text
python -m pytest
python -m pytest --cov=metricproof
python -m ruff check .
python -m ruff format --check .
pyright
python -m build
```

## Not implemented in Stage 1

- LaTeX paper scanning or parsing
- JSON, YAML, or CSV experiment ingestion
- Claim discovery, linking, or migration
- The five MetricProof consistency rules
- JSON and HTML reports
- GitHub Actions, remote services, databases, plugins, or AI integrations