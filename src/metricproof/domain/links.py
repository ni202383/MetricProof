"""Explicit, bounded Claim-to-experiment link models."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath

from metricproof.domain.claim_identity import StableClaimId
from metricproof.domain.models import NumericUnit


class LinkScale(StrEnum):
    """Explicit conversion from a source value to a Claim comparison value."""

    IDENTITY = "identity"
    FRACTION_TO_PERCENT = "fraction_to_percent"
    PERCENT_TO_FRACTION = "percent_to_fraction"

    @property
    def multiplier(self) -> Decimal:
        return {
            LinkScale.IDENTITY: Decimal("1"),
            LinkScale.FRACTION_TO_PERCENT: Decimal("100"),
            LinkScale.PERCENT_TO_FRACTION: Decimal("0.01"),
        }[self]

    def apply(self, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("link scale inputs must be finite")
        return value * self.multiplier


class DerivedOperation(StrEnum):
    SUBTRACTION = "subtraction"
    RELATIVE_CHANGE = "relative_change"
    MEAN = "mean"
    STANDARD_DEVIATION = "standard_deviation"


class StandardDeviationMode(StrEnum):
    SAMPLE = "sample"
    POPULATION = "population"


class RoundingMode(StrEnum):
    HALF_UP = "half_up"


@dataclass(frozen=True, slots=True)
class NumericTolerance:
    """Deterministic absolute and relative numeric tolerances."""

    absolute: Decimal = Decimal("0")
    relative: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        if not self.absolute.is_finite() or not self.relative.is_finite():
            raise ValueError("numeric tolerances must be finite")
        if self.absolute < 0 or self.relative < 0:
            raise ValueError("numeric tolerances must be non-negative")


@dataclass(frozen=True, slots=True)
class MetricReference:
    """One explicit experiment metric selector without filesystem behavior."""

    source_file: str
    run_id: str
    metric_name: str
    source_selector: str
    scale: LinkScale = LinkScale.IDENTITY

    def __post_init__(self) -> None:
        _validate_project_path(self.source_file)
        if not self.run_id.strip():
            raise ValueError("metric reference run_id must not be empty")
        if not self.metric_name.strip():
            raise ValueError("metric reference metric_name must not be empty")
        if not self.source_selector.strip():
            raise ValueError("metric reference source_selector must not be empty")


@dataclass(frozen=True, slots=True)
class DirectLink:
    """A user-confirmed direct Claim-to-metric relationship."""

    claim_id: StableClaimId
    metric: MetricReference
    confirmed_fingerprint: str
    tolerance_override: NumericTolerance | None = None
    note: str = ""

    def __post_init__(self) -> None:
        _validate_fingerprint_digest(self.confirmed_fingerprint)


@dataclass(frozen=True, slots=True)
class DerivedOperand:
    """One named operand of a bounded, single-layer derived operation."""

    name: str
    metric: MetricReference

    def __post_init__(self) -> None:
        if not self.name.strip() or re.fullmatch(r"[a-z][a-z0-9_]*", self.name) is None:
            raise ValueError("derived operand names must use lowercase snake_case")


@dataclass(frozen=True, slots=True)
class RoundingPolicy:
    """Optional display rounding retained as data, never executable code."""

    decimal_places: int | None = None
    mode: RoundingMode = RoundingMode.HALF_UP

    def __post_init__(self) -> None:
        if self.decimal_places is not None and self.decimal_places < 0:
            raise ValueError("rounding decimal_places must be non-negative")

    def apply(self, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("rounding inputs must be finite")
        if self.decimal_places is None:
            return value
        quantum = Decimal(1).scaleb(-self.decimal_places)
        if self.mode is not RoundingMode.HALF_UP:
            raise ValueError(f"unsupported rounding mode: {self.mode!r}")
        return value.quantize(quantum, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class DerivedLink:
    """A user-confirmed, single-layer operation over explicit metric operands."""

    claim_id: StableClaimId
    operation: DerivedOperation
    operands: tuple[DerivedOperand, ...]
    output_unit: NumericUnit
    output_scale: LinkScale
    confirmed_fingerprint: str
    rounding: RoundingPolicy = field(default_factory=RoundingPolicy)
    standard_deviation_mode: StandardDeviationMode | None = None
    tolerance_override: NumericTolerance | None = None
    note: str = ""

    def __post_init__(self) -> None:
        _validate_fingerprint_digest(self.confirmed_fingerprint)
        names = tuple(operand.name for operand in self.operands)
        if tuple(sorted(set(names))) != names:
            raise ValueError("derived operands must have unique names in stable ordering")
        if self.operation in {DerivedOperation.SUBTRACTION, DerivedOperation.RELATIVE_CHANGE}:
            if names != ("baseline", "candidate"):
                raise ValueError(
                    "subtraction and relative_change require baseline and candidate operands"
                )
        elif self.operation is DerivedOperation.MEAN:
            if not self.operands:
                raise ValueError("mean requires at least one operand")
        elif self.operation is DerivedOperation.STANDARD_DEVIATION:
            if len(self.operands) < 2:
                raise ValueError("standard_deviation requires at least two operands")
            if self.standard_deviation_mode is None:
                raise ValueError("standard_deviation requires sample or population mode")
        if (
            self.operation is not DerivedOperation.STANDARD_DEVIATION
            and self.standard_deviation_mode is not None
        ):
            raise ValueError("standard deviation mode is only valid for standard_deviation")


type ClaimLink = DirectLink | DerivedLink


def metric_reference_sort_key(reference: MetricReference) -> tuple[str, str, str, str, str]:
    return (
        reference.run_id,
        reference.metric_name,
        reference.source_file,
        reference.source_selector,
        reference.scale.value,
    )


def _validate_project_path(value: str) -> None:
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or "\\" in value
    ):
        raise ValueError("link source files must be project-relative POSIX paths")


def _validate_fingerprint_digest(value: str) -> None:
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError("confirmed_fingerprint must be a SHA-256 hex digest")
