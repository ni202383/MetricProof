"""JSON, YAML, and CSV experiment reader behavior and safety tests."""

from decimal import Decimal
from pathlib import Path

import pytest

from metricproof.adapters import experiments as reader_module
from metricproof.adapters.experiments import LocalExperimentSourceReader
from metricproof.application.configuration import (
    CsvSourceOptions,
    ExperimentFormat,
    ExperimentSource,
    StructuredSourceOptions,
)


def _structured_source(
    path: str,
    format: ExperimentFormat,
    *,
    run_id: str | None = "run-a",
    records_selector: str | None = None,
    run_id_selector: str | None = None,
    metrics: tuple[tuple[str, str], ...] = (("accuracy", "metrics.accuracy"),),
    metadata: tuple[tuple[str, str], ...] = (),
) -> ExperimentSource:
    return ExperimentSource(
        path=path,
        format=format,
        run_id=run_id,
        structured=StructuredSourceOptions(
            metrics=metrics,
            metadata=metadata,
            records_selector=records_selector,
            run_id_selector=run_id_selector,
        ),
    )


def _read(tmp_path: Path, source: ExperimentSource):
    return LocalExperimentSourceReader().read(tmp_path, source)


def test_json_nested_exact_decimal_and_metadata(tmp_path: Path) -> None:
    path = tmp_path / "result.json"
    path.write_text(
        '{"metrics":{"accuracy":0.123456789012345678901},"meta":{"dataset":"cifar10","seed":7}}',
        encoding="utf-8",
    )
    result = _read(
        tmp_path,
        _structured_source(
            "result.json",
            ExperimentFormat.JSON,
            metadata=(("dataset", "meta.dataset"), ("seed", "meta.seed")),
        ),
    )
    observation = result.runs[0].observations[0]
    assert observation.value == Decimal("0.123456789012345678901")
    assert observation.raw_value == "0.123456789012345678901"
    assert observation.dataset == "cifar10"
    assert observation.seed == 7
    assert observation.source_selector == "metrics.accuracy"


def test_json_utf8_bom_is_supported(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text('\ufeff{"metrics":{"accuracy":1e-3}}', encoding="utf-8")
    result = _read(tmp_path, _structured_source("result.json", ExperimentFormat.JSON))
    assert result.runs[0].observations[0].value == Decimal("1e-3")


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ('{"metrics":{"accuracy":1},"metrics":{}}', "MPE_JSON_VALUE"),
        ('{"metrics":', "MPE_JSON_SYNTAX"),
        ('{"metrics":{"accuracy":NaN}}', "MPE_JSON_VALUE"),
        ('{"metrics":{"accuracy":true}}', "MPE_INVALID_NUMBER"),
        ('{"metrics":{"accuracy":[1,2]}}', "MPE_INVALID_NUMBER"),
    ],
)
def test_json_reports_controlled_errors(tmp_path: Path, text: str, code: str) -> None:
    (tmp_path / "result.json").write_text(text, encoding="utf-8")
    result = _read(tmp_path, _structured_source("result.json", ExperimentFormat.JSON))
    assert result.diagnostics[0].code == code


def test_json_explicit_record_array_and_duplicate_run_id(tmp_path: Path) -> None:
    (tmp_path / "result.json").write_text(
        '{"runs":[{"id":"same","metrics":{"accuracy":1}},{"id":"same","metrics":{"accuracy":2}}]}',
        encoding="utf-8",
    )
    source = _structured_source(
        "result.json",
        ExperimentFormat.JSON,
        run_id=None,
        records_selector="runs",
        run_id_selector="id",
    )
    result = _read(tmp_path, source)
    assert len(result.runs) == 1
    assert any(item.code == "MPE_DUPLICATE_RUN_ID" for item in result.diagnostics)


def test_yaml_exact_number_anchor_and_date_metadata(tmp_path: Path) -> None:
    (tmp_path / "result.yml").write_text(
        "metrics: &metrics\n  accuracy: 0.10000000000000000001\n"
        "copy: *metrics\nmeta:\n  date: 2026-07-16\n",
        encoding="utf-8",
    )
    source = _structured_source(
        "result.yml",
        ExperimentFormat.YAML,
        metadata=(("date", "meta.date"),),
    )
    result = _read(tmp_path, source)
    assert result.runs[0].observations[0].value == Decimal("0.10000000000000000001")
    assert any(item.code == "MPE_INVALID_METADATA" for item in result.diagnostics)


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("metrics:\n  accuracy: 1\n  accuracy: 2\n", "MPE_YAML_SYNTAX"),
        ("metrics: [\n", "MPE_YAML_SYNTAX"),
        ("---\nmetrics: {accuracy: 1}\n---\nmetrics: {accuracy: 2}\n", "MPE_YAML_SYNTAX"),
        ("!!python/object/apply:os.system ['echo unsafe']\n", "MPE_YAML_SYNTAX"),
        ("root: &root\n  self: *root\nmetrics: {accuracy: 1}\n", "MPE_RECURSIVE_STRUCTURE"),
    ],
)
def test_yaml_rejects_unsafe_or_ambiguous_structures(tmp_path: Path, text: str, code: str) -> None:
    (tmp_path / "result.yml").write_text(text, encoding="utf-8")
    result = _read(tmp_path, _structured_source("result.yml", ExperimentFormat.YAML))
    assert result.diagnostics[0].code == code


def _csv_source(path: str = "results.csv") -> ExperimentSource:
    return ExperimentSource(
        path=path,
        format=ExperimentFormat.CSV,
        csv=CsvSourceOptions(
            run_id_column="run_id",
            metric_columns=("accuracy", "loss"),
            metadata_columns=("dataset", "note"),
        ),
    )


def test_csv_normalizes_rows_quotes_bom_and_metadata(tmp_path: Path) -> None:
    (tmp_path / "results.csv").write_text(
        "\ufeffrun_id,accuracy,loss,dataset,note\n"
        'b,0.90,1e-2,cifar10,"line one\nline two"\n'
        'a,0.80,0.2,cifar100,"quoted, value"\n',
        encoding="utf-8",
    )
    result = _read(tmp_path, _csv_source())
    assert [run.run_id for run in result.runs] == ["a", "b"]
    assert result.runs[1].observations[1].value == Decimal("0.01")
    assert dict(result.runs[1].metadata)["note"] == "line one\nline two"


@pytest.mark.parametrize(
    ("text", "code"),
    [
        ("", "MPE_CSV_HEADER"),
        ("run_id,accuracy,accuracy,dataset,note\na,1,2,x,y\n", "MPE_CSV_DUPLICATE_HEADER"),
        ("run_id,accuracy,dataset,note\na,1,x,y\n", "MPE_CSV_MISSING_COLUMN"),
        ("run_id,accuracy,loss,dataset,note\na,1,2,x,y\na,2,3,x,y\n", "MPE_DUPLICATE_RUN_ID"),
        ("run_id,accuracy,loss,dataset,note\na,,2,x,y\n", "MPE_INVALID_NUMBER"),
        ("run_id,accuracy,loss,dataset,note\na,wat,2,x,y\n", "MPE_INVALID_NUMBER"),
    ],
)
def test_csv_reports_structure_and_value_errors(tmp_path: Path, text: str, code: str) -> None:
    (tmp_path / "results.csv").write_text(text, encoding="utf-8")
    result = _read(tmp_path, _csv_source())
    assert any(item.code == code for item in result.diagnostics)


def test_file_size_and_path_escape_are_controlled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "result.json").write_text('{"metrics":{"accuracy":1}}', encoding="utf-8")
    monkeypatch.setattr(reader_module, "MAX_FILE_BYTES", 1)
    result = _read(tmp_path, _structured_source("result.json", ExperimentFormat.JSON))
    assert result.diagnostics[0].code == "MPE_FILE_TOO_LARGE"

    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text('{"metrics":{"accuracy":1}}', encoding="utf-8")
    result = _read(tmp_path, _structured_source("../" + outside.name, ExperimentFormat.JSON))
    assert result.diagnostics[0].code == "MPE_PATH_ESCAPE"
