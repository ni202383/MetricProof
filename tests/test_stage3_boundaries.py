"""Additional Stage 3 error, resource, and invariant boundary coverage."""

import json
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from metricproof.adapters import config as config_module
from metricproof.adapters import experiments as reader_module
from metricproof.adapters.config import YamlConfigurationRepository, find_project_root
from metricproof.adapters.experiments import LocalExperimentSourceReader
from metricproof.application.configuration import (
    CsvSourceOptions,
    ExperimentFormat,
    ExperimentSource,
    ProjectConfiguration,
    StructuredSourceOptions,
)
from metricproof.application.errors import ExitCode
from metricproof.application.experiments import load_experiments
from metricproof.application.input_errors import ProjectConfigurationError
from metricproof.application.ports import SourceReadResult
from metricproof.cli import main as cli_main
from metricproof.domain.models import (
    ExperimentRun,
    MetricObservation,
    NumericValue,
    SourceLocation,
)

runner = CliRunner()


def _config_root(tmp_path: Path, body: str) -> Path:
    (tmp_path / "result.json").write_text('{"metrics":{"value":1}}', encoding="utf-8")
    path = tmp_path / ".metricproof" / "config.yml"
    path.parent.mkdir()
    path.write_text(body, encoding="utf-8")
    return tmp_path


def _source_config(extra: str) -> str:
    return f"""schema_version: "1"
result_paths:
  - path: result.json
    format: json
{extra}
"""


@pytest.mark.parametrize(
    "extra",
    [
        "    run_id: run\n",
        "    run_id: run\n    csv:\n      run_id_column: id\n      metric_columns: [value]\n",
        "    structured:\n      metrics: {}\n    run_id: run\n",
        "    structured:\n      metrics: {value: metrics.value}\n",
        (
            "    run_id: run\n    structured:\n"
            "      metrics: {value: metrics.value}\n      run_id_selector: id\n"
        ),
        (
            "    run_id: run\n    structured:\n"
            "      metrics: {value: metrics.value}\n"
            "      records_selector: runs\n      run_id_selector: id\n"
        ),
    ],
)
def test_config_rejects_invalid_format_option_combinations(tmp_path: Path, extra: str) -> None:
    root = _config_root(tmp_path, _source_config(extra))
    with pytest.raises(ProjectConfigurationError):
        YamlConfigurationRepository().load(root)


def test_config_file_size_encoding_and_source_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _config_root(
        tmp_path,
        _source_config("    run_id: run\n    structured:\n      metrics: {value: metrics.value}"),
    )
    monkeypatch.setattr(config_module, "MAX_FILE_BYTES", 1)
    with pytest.raises(ProjectConfigurationError, match="exceeds"):
        YamlConfigurationRepository().load(root)
    monkeypatch.setattr(config_module, "MAX_FILE_BYTES", 5_000_000)
    (root / ".metricproof" / "config.yml").write_bytes(b"\xff\xfe")
    with pytest.raises(ProjectConfigurationError, match="UTF-8"):
        YamlConfigurationRepository().load(root)

    (root / "second.json").write_text("{}", encoding="utf-8")
    (root / ".metricproof" / "config.yml").write_text(
        """schema_version: "1"
result_paths:
  - path: "*.json"
    format: json
    run_id: run
    structured:
      metrics: {value: metrics.value}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_module, "MAX_EXPERIMENT_SOURCES", 1)
    with pytest.raises(ProjectConfigurationError, match="more than"):
        YamlConfigurationRepository().load(root)


def test_config_preserves_declared_experiment_config_and_finds_root(tmp_path: Path) -> None:
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "run.yml").write_text("seed: 7\n", encoding="utf-8")
    root = _config_root(
        tmp_path,
        """schema_version: "1"
result_paths:
  - path: result.json
    format: json
    run_id: run
    config_reference: configs/run.yml
    structured:
      metrics: {value: metrics.value}
experiment_config_paths: [configs/*.yml]
""",
    )
    nested = root / "nested" / "deeper"
    nested.mkdir(parents=True)
    config = YamlConfigurationRepository().load(root)
    assert config.experiment_config_paths == ("configs/run.yml",)
    assert config.sources[0].config_reference == "configs/run.yml"
    assert find_project_root(nested) == root


def test_config_rejects_directory_source(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()
    config_path = tmp_path / ".metricproof" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text(
        """schema_version: "1"
result_paths:
  - path: results
    format: json
    run_id: run
    structured:
      metrics: {value: metrics.value}
""",
        encoding="utf-8",
    )
    with pytest.raises(ProjectConfigurationError, match="not a file"):
        YamlConfigurationRepository().load(tmp_path)


def _structured_source(
    path: str,
    *,
    run_id: str | None = "run",
    records_selector: str | None = None,
    run_id_selector: str | None = None,
    metric_selector: str = "metrics.value",
    metadata: tuple[tuple[str, str], ...] = (),
) -> ExperimentSource:
    return ExperimentSource(
        path=path,
        format=ExperimentFormat.JSON,
        run_id=run_id,
        structured=StructuredSourceOptions(
            metrics=(("value", metric_selector),),
            metadata=metadata,
            records_selector=records_selector,
            run_id_selector=run_id_selector,
        ),
    )


def test_reader_reports_missing_directory_and_encoding_sources(tmp_path: Path) -> None:
    reader = LocalExperimentSourceReader()
    missing = reader.read(tmp_path, _structured_source("missing.json"))
    assert missing.diagnostics[0].code == "MPE_SOURCE_NOT_FOUND"

    (tmp_path / "directory.json").mkdir()
    directory = reader.read(tmp_path, _structured_source("directory.json"))
    assert directory.diagnostics[0].code == "MPE_SOURCE_NOT_FILE"

    (tmp_path / "encoded.json").write_bytes(b"\xff\xfe")
    encoded = reader.read(tmp_path, _structured_source("encoded.json"))
    assert encoded.diagnostics[0].code == "MPE_ENCODING_ERROR"


@pytest.mark.parametrize(
    ("payload", "source", "code"),
    [
        ("[]", _structured_source("result.json"), "MPE_ROOT_TYPE"),
        (
            '{"runs": {}}',
            _structured_source(
                "result.json", run_id=None, records_selector="runs", run_id_selector="id"
            ),
            "MPE_RECORDS_TYPE",
        ),
        (
            '{"runs": [1]}',
            _structured_source(
                "result.json", run_id=None, records_selector="runs", run_id_selector="id"
            ),
            "MPE_RECORD_TYPE",
        ),
        (
            '{"id": true, "metrics": {"value": 1}}',
            _structured_source("result.json", run_id=None, run_id_selector="id"),
            "MPE_INVALID_RUN_ID",
        ),
        (
            '{"metrics": {}}',
            _structured_source("result.json"),
            "MPE_SELECTOR_NOT_FOUND",
        ),
        (
            '{"metrics": 1}',
            _structured_source("result.json"),
            "MPE_SELECTOR_TYPE",
        ),
    ],
)
def test_reader_reports_root_record_run_and_selector_errors(
    tmp_path: Path,
    payload: str,
    source: ExperimentSource,
    code: str,
) -> None:
    (tmp_path / "result.json").write_text(payload, encoding="utf-8")
    result = LocalExperimentSourceReader().read(tmp_path, source)
    assert any(item.code == code for item in result.diagnostics)


def test_reader_supports_explicit_array_index_and_reports_out_of_range(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text('{"values":[1,2]}', encoding="utf-8")
    reader = LocalExperimentSourceReader()
    valid = reader.read(tmp_path, _structured_source("result.json", metric_selector="values.1"))
    assert valid.runs[0].observations[0].value == Decimal("2")
    invalid = reader.read(tmp_path, _structured_source("result.json", metric_selector="values.9"))
    assert invalid.diagnostics[0].code == "MPE_SELECTOR_NOT_FOUND"


def test_reader_enforces_nesting_and_non_string_yaml_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "result.json").write_text('{"a":{"b":{"c":1}}}', encoding="utf-8")
    monkeypatch.setattr(reader_module, "MAX_NESTING_DEPTH", 1)
    nested = LocalExperimentSourceReader().read(
        tmp_path, _structured_source("result.json", metric_selector="a.b.c")
    )
    assert nested.diagnostics[0].code == "MPE_NESTING_LIMIT"

    (tmp_path / "result.yml").write_text("1: value\nmetrics: {value: 1}\n", encoding="utf-8")
    yaml_source = ExperimentSource(
        path="result.yml",
        format=ExperimentFormat.YAML,
        run_id="run",
        structured=StructuredSourceOptions(metrics=(("value", "metrics.value"),)),
    )
    non_string = LocalExperimentSourceReader().read(tmp_path, yaml_source)
    assert non_string.diagnostics[0].code == "MPE_NON_STRING_KEY"


def _csv_source() -> ExperimentSource:
    return ExperimentSource(
        path="results.csv",
        format=ExperimentFormat.CSV,
        csv=CsvSourceOptions(
            run_id_column="run_id",
            metric_columns=("value",),
            metadata_columns=("dataset",),
        ),
    )


def test_csv_undeclared_row_width_row_limit_and_syntax(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader = LocalExperimentSourceReader()
    (tmp_path / "results.csv").write_text(
        "run_id,value,dataset,extra\na,1,x,ignored\n", encoding="utf-8"
    )
    warning = reader.read(tmp_path, _csv_source())
    assert warning.diagnostics[0].code == "MPW_CSV_UNDECLARED_COLUMNS"

    (tmp_path / "results.csv").write_text("run_id,value,dataset\na,1\n", encoding="utf-8")
    width = reader.read(tmp_path, _csv_source())
    assert width.diagnostics[0].code == "MPE_CSV_ROW_WIDTH"

    (tmp_path / "results.csv").write_text("run_id,value,dataset\na,1,x\nb,2,y\n", encoding="utf-8")
    monkeypatch.setattr(reader_module, "MAX_CSV_ROWS", 1)
    limited = reader.read(tmp_path, _csv_source())
    assert any(item.code == "MPE_CSV_ROW_LIMIT" for item in limited.diagnostics)

    monkeypatch.setattr(reader_module, "MAX_CSV_ROWS", 100_000)
    (tmp_path / "results.csv").write_text(
        'run_id,value,dataset\na,"unterminated,x\n', encoding="utf-8"
    )
    syntax = reader.read(tmp_path, _csv_source())
    assert syntax.diagnostics[0].code == "MPE_CSV_SYNTAX"


def _run(
    source: str,
    *,
    metadata: tuple[tuple[str, str], ...] = (),
    config_reference: str | None = None,
) -> ExperimentRun:
    location = SourceLocation(source, "metrics.value")
    observation = MetricObservation.create(
        run_id="run",
        metric_name=source,
        numeric=NumericValue("1", Decimal("1")),
        source_file=source,
        source_selector="metrics.value",
        location=location,
        config_reference=config_reference,
        metadata=metadata,
    )
    return ExperimentRun(
        run_id="run",
        observations=(observation,),
        metadata=metadata,
        result_sources=(source,),
        config_reference=config_reference,
    )


class _ConflictReader:
    def read(self, project_root: Path, source: ExperimentSource) -> SourceReadResult:
        metadata = (("dataset", "a" if source.path == "a" else "b"),)
        config = "a.yml" if source.path == "a" else "b.yml"
        return SourceReadResult((_run(source.path, metadata=metadata, config_reference=config),))


def test_application_reports_metadata_and_config_reference_conflicts(tmp_path: Path) -> None:
    sources = (
        ExperimentSource("a", ExperimentFormat.JSON),
        ExperimentSource("b", ExperimentFormat.JSON),
    )
    catalog = load_experiments(tmp_path, ProjectConfiguration("1", sources), _ConflictReader())
    codes = {item.code for item in catalog.diagnostics}
    assert "MPE_METADATA_CONFLICT" in codes
    assert "MPE_CONFIG_REFERENCE_CONFLICT" in codes


def test_domain_invariants_reject_invalid_locations_and_values() -> None:
    with pytest.raises(ValueError):
        SourceLocation("../outside")
    with pytest.raises(ValueError):
        SourceLocation("result.json", line=0)
    with pytest.raises(ValueError):
        NumericValue("NaN", Decimal("NaN"))
    location = SourceLocation(
        "result.csv",
        line=2,
        column=3,
        end_line=2,
        end_column=5,
        char_start=4,
        char_end=8,
    )
    assert location.char_end == 8
    with pytest.raises(ValueError):
        SourceLocation("result.csv", line=2, end_line=1)
    with pytest.raises(ValueError):
        SourceLocation("result.csv", char_start=4, char_end=4)


def test_experiments_cli_maps_interrupt_and_internal_error_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def interrupt():
        raise KeyboardInterrupt

    monkeypatch.setattr(cli_main, "_load_catalog", interrupt)
    interrupted = runner.invoke(cli_main.app, ["experiments", "validate"])
    assert interrupted.exit_code == ExitCode.INTERRUPTED
    assert "MP_INTERRUPTED" in interrupted.stderr

    def internal():
        raise RuntimeError("secret detail")

    monkeypatch.setattr(cli_main, "_load_catalog", internal)
    failed = runner.invoke(cli_main.app, ["experiments", "validate", "--json"])
    assert failed.exit_code == ExitCode.INTERNAL_ERROR
    assert failed.stderr == ""
    assert "secret detail" not in failed.stdout
    assert json.loads(failed.stdout)["error"]["code"] == "MP_INTERNAL"
