"""Safe JSON/YAML readers for explicit experiment comparison snapshots."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

import yaml

from metricproof.adapters.limits import MAX_FILE_BYTES, MAX_NESTING_DEPTH
from metricproof.adapters.yaml_support import load_single_yaml
from metricproof.application.ports import ConfigSnapshotReadResult
from metricproof.domain.models import ExperimentRun, Severity, SourceLocation, make_input_diagnostic
from metricproof.domain.numeric import DecimalToken
from metricproof.domain.stage6 import (
    ConfigValue,
    ConfigValueKind,
    ExperimentConfigSnapshot,
)


@dataclass(frozen=True, slots=True)
class _ConfigProblem(Exception):
    code: str
    message: str
    remediation: str


class LocalExperimentConfigReader:
    """Read selected paths without importing, evaluating, or executing configuration files."""

    def read(
        self,
        project_root: Path,
        run: ExperimentRun,
        controlled_keys: tuple[str, ...],
    ) -> ConfigSnapshotReadResult:
        reference = run.config_reference
        if reference is None:
            return ConfigSnapshotReadResult(())
        try:
            parsed = _load(project_root, reference)
            values = tuple((key, _selected_value(parsed, key)) for key in controlled_keys)
            return ConfigSnapshotReadResult(
                (ExperimentConfigSnapshot(run.run_id, reference, values),)
            )
        except _ConfigProblem as problem:
            diagnostic = make_input_diagnostic(
                code=problem.code,
                severity=Severity.ERROR,
                message=problem.message,
                location=SourceLocation(reference),
                remediation=problem.remediation,
                evidence_details=(f"run={run.run_id}", f"config_reference={reference}"),
            )
            return ConfigSnapshotReadResult((), (diagnostic,))


def _load(project_root: Path, reference: str) -> object:
    root = project_root.resolve(strict=True)
    candidate = root / reference
    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as error:
        raise _ConfigProblem(
            "MPE_CONFIG_NOT_FOUND",
            f"Experiment configuration does not exist: {reference}",
            "Restore the referenced JSON/YAML configuration file.",
        ) from error
    if not _is_within(resolved, root) or not resolved.is_file():
        raise _ConfigProblem(
            "MPE_CONFIG_PATH_ESCAPE",
            f"Experiment configuration is outside the project boundary: {reference}",
            "Use a regular project-relative JSON/YAML file.",
        )
    if resolved.stat().st_size > MAX_FILE_BYTES:
        raise _ConfigProblem(
            "MPE_CONFIG_TOO_LARGE",
            f"Experiment configuration exceeds {MAX_FILE_BYTES} bytes: {reference}",
            "Reduce or split the configuration file.",
        )
    try:
        text = resolved.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError) as error:
        raise _ConfigProblem(
            "MPE_CONFIG_READ_ERROR",
            f"Experiment configuration could not be read as UTF-8: {error}",
            "Check the path, permissions, and UTF-8 encoding.",
        ) from error
    suffix = resolved.suffix.casefold()
    try:
        if suffix == ".json":
            parsed = cast(
                object,
                json.loads(
                    text,
                    parse_float=_decimal_token,
                    parse_int=_decimal_token,
                    parse_constant=_reject_constant,
                    object_pairs_hook=_unique_object,
                ),
            )
        elif suffix in {".yml", ".yaml"}:
            parsed = load_single_yaml(text, exact_numbers=True)
        else:
            raise _ConfigProblem(
                "MPE_CONFIG_FORMAT",
                f"Unsupported experiment configuration format: {suffix or '<none>'}",
                "Use a .json, .yml, or .yaml configuration file.",
            )
    except _ConfigProblem:
        raise
    except (json.JSONDecodeError, yaml.YAMLError, ValueError, InvalidOperation) as error:
        raise _ConfigProblem(
            "MPE_CONFIG_SYNTAX",
            f"Invalid safe experiment configuration: {error}",
            "Fix the syntax, duplicate keys, unsafe YAML tags, or non-finite numbers.",
        ) from error
    _validate(parsed)
    return parsed


def _selected_value(root: object, path: str) -> ConfigValue | None:
    current = root
    for part in path.split("."):
        if not part:
            return None
        if isinstance(current, Mapping):
            mapping = cast(Mapping[str, object], current)
            if part not in mapping:
                return None
            current = mapping[part]
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes):
            try:
                current = cast(Sequence[object], current)[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return _config_value(current)


def _config_value(value: object) -> ConfigValue:
    if value is None:
        return ConfigValue(ConfigValueKind.NULL)
    if isinstance(value, bool):
        return ConfigValue(ConfigValueKind.BOOLEAN, scalar=value)
    if isinstance(value, DecimalToken):
        return ConfigValue(ConfigValueKind.NUMBER, scalar=value.value)
    if isinstance(value, Decimal):
        return ConfigValue(ConfigValueKind.NUMBER, scalar=value)
    if isinstance(value, str):
        return ConfigValue(ConfigValueKind.STRING, scalar=value)
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return ConfigValue(
            ConfigValueKind.LIST,
            items=tuple(_config_value(item) for item in cast(Sequence[object], value)),
        )
    if isinstance(value, Mapping):
        mapping = cast(Mapping[str, object], value)
        return ConfigValue(
            ConfigValueKind.MAPPING,
            entries=tuple((key, _config_value(item)) for key, item in sorted(mapping.items())),
        )
    raise _ConfigProblem(
        "MPE_CONFIG_VALUE",
        f"Unsupported experiment configuration value: {type(value).__name__}",
        "Use JSON/YAML null, booleans, strings, finite numbers, lists, or mappings.",
    )


def _validate(value: object) -> None:
    active: set[int] = set()

    def visit(current: object, depth: int) -> None:
        if depth > MAX_NESTING_DEPTH:
            raise _ConfigProblem(
                "MPE_CONFIG_NESTING",
                f"Experiment configuration exceeds nesting depth {MAX_NESTING_DEPTH}.",
                "Flatten the configuration structure.",
            )
        if isinstance(current, Mapping):
            mapping = cast(Mapping[object, object], current)
            if id(mapping) in active:
                raise _ConfigProblem(
                    "MPE_CONFIG_RECURSIVE",
                    "Recursive YAML configuration structures are not supported.",
                    "Replace aliases with a finite mapping.",
                )
            active.add(id(mapping))
            for key, nested in mapping.items():
                if not isinstance(key, str):
                    raise _ConfigProblem(
                        "MPE_CONFIG_KEY",
                        "Experiment configuration mapping keys must be strings.",
                        "Use string keys for controlled dot paths.",
                    )
                visit(nested, depth + 1)
            active.remove(id(mapping))
        elif isinstance(current, Sequence) and not isinstance(current, str | bytes):
            sequence = cast(Sequence[object], current)
            if id(sequence) in active:
                raise _ConfigProblem(
                    "MPE_CONFIG_RECURSIVE",
                    "Recursive YAML configuration arrays are not supported.",
                    "Replace aliases with a finite list.",
                )
            active.add(id(sequence))
            for nested in sequence:
                visit(nested, depth + 1)
            active.remove(id(sequence))

    visit(value, 0)


def _decimal_token(raw: str) -> DecimalToken:
    value = Decimal(raw)
    if not value.is_finite():
        raise ValueError("non-finite number")
    return DecimalToken(raw_text=raw, value=value)


def _reject_constant(raw: str) -> object:
    raise ValueError(f"non-finite constant {raw!r} is not supported")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate object key {key!r}")
        result[key] = value
    return result


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
