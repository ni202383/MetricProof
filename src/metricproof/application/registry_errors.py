"""Typed expected failures for the persistent Claim registry boundary."""

from metricproof.application.errors import ExitCode, MetricProofError


class ClaimRegistryError(MetricProofError):
    """A strict claims.yml syntax, schema, path, or atomic-write failure."""

    def __init__(
        self,
        *,
        file: str,
        field: str,
        reason: str,
        remediation: str,
        exit_code: ExitCode = ExitCode.INPUT_ERROR,
    ) -> None:
        location = file if not field else f"{file}:{field}"
        super().__init__(
            f"{location}: {reason} Suggested fix: {remediation}",
            exit_code,
        )
        self.file = file
        self.field = field
        self.reason = reason
        self.remediation = remediation
