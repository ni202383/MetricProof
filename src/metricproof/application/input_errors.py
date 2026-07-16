"""Typed expected errors for project configuration and input discovery."""

from metricproof.application.errors import ExitCode, MetricProofError


class ProjectConfigurationError(MetricProofError):
    """A strict config.yml schema, syntax, or path error."""

    def __init__(self, *, file: str, field: str, reason: str, remediation: str) -> None:
        location = file if not field else f"{file}:{field}"
        super().__init__(
            f"{location}: {reason} Suggested fix: {remediation}",
            ExitCode.USAGE_ERROR,
        )
        self.file = file
        self.field = field
        self.reason = reason
        self.remediation = remediation
