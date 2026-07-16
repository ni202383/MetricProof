"""Package metadata tests."""

import metricproof


def test_package_import_and_version() -> None:
    assert metricproof.__version__ == "0.1.0.dev0"
