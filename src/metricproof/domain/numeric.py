"""Deterministic conversion of lexical numbers to finite Decimal values."""

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from metricproof.domain.models import NumericValue


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
    return NumericValue(raw_text=raw_text, parsed=parsed)
