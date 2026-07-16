"""Stable process exit codes and user-facing application errors."""

from enum import IntEnum


class ExitCode(IntEnum):
    """Process exit codes reserved by the MetricProof specification."""

    SUCCESS = 0
    ANALYSIS_FAILURE = 1
    USAGE_ERROR = 2
    INPUT_ERROR = 3
    ENVIRONMENT_ERROR = 4
    INTERNAL_ERROR = 5
    INTERRUPTED = 130


class MetricProofError(Exception):
    """An expected error that can be shown without a Python traceback."""

    def __init__(self, message: str, exit_code: ExitCode) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
