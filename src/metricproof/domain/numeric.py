"""Deterministic conversion of lexical numbers to finite Decimal values."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from metricproof.domain.models import NumericKind, NumericValue


@dataclass(frozen=True, slots=True)
class DecimalToken:
    """A number parsed by a format adapter without passing through float."""

    raw_text: str
    value: Decimal


class NumericParseError(ValueError):
    """A controlled reason why an input is not a valid metric number."""


def parse_numeric(value: object) -> NumericValue:
    """Parse supported exact numeric inputs, rejecting booleans and floats."""

    if isinstance(value, bool):
        raise NumericParseError("boolean values are not metric numbers")
    if isinstance(value, DecimalToken):
        raw_text = value.raw_text
        parsed = value.value
    elif isinstance(value, Decimal):
        raw_text = str(value)
        parsed = value
    elif isinstance(value, int):
        raw_text = str(value)
        parsed = Decimal(value)
    elif isinstance(value, str):
        raw_text = value
        if not value.strip():
            raise NumericParseError("empty strings are not metric numbers")
        try:
            parsed = Decimal(value.strip())
        except InvalidOperation as error:
            raise NumericParseError(f"invalid decimal text: {value!r}") from error
    elif isinstance(value, float):
        raise NumericParseError("binary floating-point values are not accepted")
    else:
        raise NumericParseError(f"unsupported numeric type: {type(value).__name__}")

    if not parsed.is_finite():
        raise NumericParseError("NaN and Infinity are not valid metric numbers")
    kind = (
        NumericKind.SCIENTIFIC
        if "e" in raw_text.casefold()
        else NumericKind.DECIMAL
        if "." in raw_text
        else NumericKind.INTEGER
    )
    decimal_places = _decimal_places(raw_text)
    return NumericValue(
        raw_text=raw_text,
        parsed=parsed,
        kind=kind,
        decimal_places=decimal_places,
    )


def _decimal_places(raw_text: str) -> int | None:
    mantissa = raw_text.strip().lstrip("+-").split("e", maxsplit=1)[0].split("E", maxsplit=1)[0]
    if "." not in mantissa:
        return 0
    return len(mantissa.partition(".")[2])
