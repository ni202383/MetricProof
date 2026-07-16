"""Strict config.yml schema and project-path boundary tests."""

from pathlib import Path

import pytest

from metricproof.adapters.config import YamlConfigurationRepository
from metricproof.application.input_errors import ProjectConfigurationError


def _write_project(tmp_path: Path, config: str, *, result_name: str = "runs/result.json") -> Path:
    result = tmp_path / result_name
    result.parent.mkdir(parents=True, exist_ok=True)
    result.write_text('{"metrics": {"accuracy": 0.9}}', encoding="utf-8")
    config_path = tmp_path / ".metricproof" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text(config, encoding="utf-8")
    return tmp_path


def _minimal(path: str = "runs/result.json") -> str:
    return f"""schema_version: "1"
result_paths:
  - path: {path}
    format: json
    run_id: baseline
    structured:
      metrics:
        accuracy: metrics.accuracy
"""


def test_load_minimal_config_and_windows_separator(tmp_path: Path) -> None:
    root = _write_project(tmp_path, _minimal(r"runs\result.json"))
    config = YamlConfigurationRepository().load(root)
    assert config.schema_version == "1"
    assert [source.path for source in config.sources] == ["runs/result.json"]
    assert config.sources[0].structured is not None
    assert config.sources[0].structured.metrics == (("accuracy", "metrics.accuracy"),)


def test_config_glob_expands_in_stable_order_and_excludes(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    for name in ("z.json", "a.json", "skip.json"):
        (tmp_path / "runs" / name).write_text('{"metrics": {"accuracy": 1}}', encoding="utf-8")
    config_path = tmp_path / ".metricproof" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text(
        _minimal("runs/*.json") + "exclude_paths:\n  - runs/skip.json\n",
        encoding="utf-8",
    )
    config = YamlConfigurationRepository().load(tmp_path)
    assert [source.path for source in config.sources] == ["runs/a.json", "runs/z.json"]


@pytest.mark.parametrize(
    ("config", "fragment"),
    [
        ('schema_version: "1"\nresult_paths: [', "invalid safe YAML"),
        (_minimal() + "unknown: true\n", "unknown"),
        (_minimal().replace("      metrics:", "      unknown: true\n      metrics:"), "unknown"),
        (_minimal().replace('schema_version: "1"\n', ""), "schema_version"),
        (_minimal().replace('schema_version: "1"', 'schema_version: "2"'), "unsupported"),
        (_minimal().replace("format: json", "format: pickle"), "format"),
        (
            _minimal().replace(
                "metrics:\n",
                "metrics:\n        accuracy: metrics.accuracy\n        accuracy: metrics.other\n",
            ),
            "duplicate",
        ),
        (_minimal() + "!!python/object:os.system {}\n", "invalid safe YAML"),
    ],
)
def test_config_rejects_schema_and_yaml_errors(tmp_path: Path, config: str, fragment: str) -> None:
    root = _write_project(tmp_path, config)
    with pytest.raises(ProjectConfigurationError, match=fragment):
        YamlConfigurationRepository().load(root)


def test_missing_config_is_usage_error(tmp_path: Path) -> None:
    with pytest.raises(ProjectConfigurationError, match="does not exist"):
        YamlConfigurationRepository().load(tmp_path)


@pytest.mark.parametrize("path", ["../outside.json", "C:/outside.json", r"C:\outside.json"])
def test_config_rejects_absolute_and_parent_paths(tmp_path: Path, path: str) -> None:
    root = _write_project(tmp_path, _minimal(path))
    with pytest.raises(ProjectConfigurationError, match="not allowed"):
        YamlConfigurationRepository().load(root)


def test_config_rejects_missing_source(tmp_path: Path) -> None:
    root = _write_project(tmp_path, _minimal("runs/missing.json"))
    with pytest.raises(ProjectConfigurationError, match="does not match"):
        YamlConfigurationRepository().load(root)


def test_config_rejects_overlapping_source_aliases(tmp_path: Path) -> None:
    config = (
        _minimal()
        + """  - path: runs/*.json
    format: json
    run_id: duplicate
    structured:
      metrics:
        accuracy: metrics.accuracy
"""
    )
    root = _write_project(tmp_path, config)
    with pytest.raises(ProjectConfigurationError, match="already declared"):
        YamlConfigurationRepository().load(root)


def test_config_rejects_csv_column_role_conflicts(tmp_path: Path) -> None:
    root = _write_project(
        tmp_path,
        """schema_version: "1"
result_paths:
  - path: runs/result.json
    format: csv
    csv:
      run_id_column: run_id
      metric_columns: [accuracy]
      metadata_columns: [accuracy]
""",
    )
    with pytest.raises(ProjectConfigurationError, match="overlap"):
        YamlConfigurationRepository().load(root)


def test_config_rejects_symlink_escape_when_supported(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
    outside.write_text("{}", encoding="utf-8")
    link = tmp_path / "runs" / "linked.json"
    link.parent.mkdir()
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    config_path = tmp_path / ".metricproof" / "config.yml"
    config_path.parent.mkdir()
    config_path.write_text(_minimal("runs/linked.json"), encoding="utf-8")
    with pytest.raises(ProjectConfigurationError, match="escapes"):
        YamlConfigurationRepository().load(tmp_path)
