"""End-to-end Stage 3 normalization of JSON, YAML, and CSV together."""

from decimal import Decimal
from pathlib import Path

from metricproof.adapters.config import YamlConfigurationRepository
from metricproof.adapters.experiments import LocalExperimentSourceReader
from metricproof.application.experiments import load_experiments


def test_three_declared_formats_normalize_into_one_catalog(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    (runs / "baseline.json").write_text(
        '{"metrics":{"accuracy":0.841},"meta":{"commit":"abc123"}}',
        encoding="utf-8",
    )
    (runs / "proposed.yml").write_text(
        "metrics:\n  accuracy: 0.872\nmeta:\n  commit: def456\n",
        encoding="utf-8",
    )
    (runs / "seeds.csv").write_text(
        "run_id,accuracy,seed\nseed-1,0.871,1\nseed-2,0.873,2\n",
        encoding="utf-8",
    )
    config = tmp_path / ".metricproof" / "config.yml"
    config.parent.mkdir()
    config.write_text(
        """schema_version: "1"
result_paths:
  - path: runs/baseline.json
    format: json
    run_id: baseline
    structured:
      metrics: {accuracy: metrics.accuracy}
      metadata: {commit: meta.commit}
  - path: runs/proposed.yml
    format: yaml
    run_id: proposed
    structured:
      metrics: {accuracy: metrics.accuracy}
      metadata: {commit: meta.commit}
  - path: runs/seeds.csv
    format: csv
    csv:
      run_id_column: run_id
      metric_columns: [accuracy]
      metadata_columns: [seed]
""",
        encoding="utf-8",
    )

    configuration = YamlConfigurationRepository().load(tmp_path)
    catalog = load_experiments(tmp_path, configuration, LocalExperimentSourceReader())

    assert not catalog.has_blocking_errors
    assert [run.run_id for run in catalog.runs] == ["baseline", "proposed", "seed-1", "seed-2"]
    assert [observation.value for observation in catalog.observations] == [
        Decimal("0.841"),
        Decimal("0.872"),
        Decimal("0.871"),
        Decimal("0.873"),
    ]
    assert catalog.runs[0].declared_commit == "abc123"
    assert catalog.runs[1].declared_commit == "def456"
