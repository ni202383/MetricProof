"""Strict normalization for Claim-classification configuration terms."""

from __future__ import annotations

from metricproof.application.input_errors import ProjectConfigurationError


def normalize_metric_aliases(
    raw_aliases: dict[str, list[str]],
    *,
    config_file: str,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Normalize aliases and reject empty or cross-metric duplicates."""

    normalized: list[tuple[str, tuple[str, ...]]] = []
    observed: dict[str, str] = {}
    for metric, aliases in sorted(raw_aliases.items(), key=lambda item: item[0].casefold()):
        canonical = " ".join(metric.split())
        if not canonical:
            raise _alias_error(
                config_file,
                "metric_aliases",
                "metric names must not be empty",
                "use a non-empty canonical metric name",
            )
        values: list[str] = []
        for index, value in enumerate(aliases):
            alias = " ".join(value.split())
            if not alias:
                raise _alias_error(
                    config_file,
                    f"metric_aliases.{metric}.{index}",
                    "metric aliases must not be empty",
                    "remove empty aliases",
                )
            key = alias.casefold()
            previous = observed.get(key)
            if previous is not None and previous != canonical:
                raise _alias_error(
                    config_file,
                    f"metric_aliases.{metric}.{index}",
                    f"metric alias {alias!r} is already assigned to {previous!r}",
                    "use each case-insensitive metric alias for only one metric",
                )
            observed[key] = canonical
            if key != canonical.casefold() and key not in {
                existing.casefold() for existing in values
            }:
                values.append(alias)
        canonical_key = canonical.casefold()
        previous = observed.get(canonical_key)
        if previous is not None and previous != canonical:
            raise _alias_error(
                config_file,
                f"metric_aliases.{metric}",
                f"metric name {canonical!r} is already assigned to {previous!r}",
                "use unique case-insensitive canonical metric names and aliases",
            )
        observed[canonical_key] = canonical
        normalized.append((canonical, tuple(sorted(values, key=lambda item: item.casefold()))))
    return tuple(normalized)


def _alias_error(
    file: str,
    field: str,
    reason: str,
    remediation: str,
) -> ProjectConfigurationError:
    return ProjectConfigurationError(
        file=file,
        field=field,
        reason=reason,
        remediation=remediation,
    )
