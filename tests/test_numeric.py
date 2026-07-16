"""Exact experiment numeric conversion tests."""

from decimal import Decimal

import pytest

from metricproof.domain.numeric import DecimalToken, NumericParseError, parse_numeric


@pytest.mark.parametrize(
    ("value", "expected", "raw"),
    [
        (0, Decimal("0"), "0"),
        (-12, Decimal("-12"), "-12"),
        ("0.123456789012345678901", Decimal("0.123456789012345678901"), "0.123456789012345678901"),
        ("1.25e-7", Decimal("1.25e-7"), "1.25e-7"),
        (Decimal("4.50"), Decimal("4.50"), "4.50"),
        (DecimalToken("6.02E23", Decimal("6.02E23")), Decimal("6.02E23"), "6.02E23"),
    ],
)
def test_parse_numeric_preserves_exact_decimal(value: object, expected: Decimal, raw: str) -> None:
    numeric = parse_numeric(value)
    assert numeric.parsed == expected
    assert numeric.raw_text == raw


@pytest.mark.parametrize("value", [True, False, 0.1, "", " ", "NaN", "Infinity", "-Infinity"])
def test_parse_numeric_rejects_unsafe_or_non_finite_values(value: object) -> None:
    with pytest.raises(NumericParseError):
        parse_numeric(value)
