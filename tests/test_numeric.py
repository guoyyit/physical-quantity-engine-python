from decimal import Decimal

import pytest

from pqe.errors import EngineError, ErrorCode
from pqe.numeric import (
    format_decimal,
    round_result,
    round_uncertainty,
    to_decimal,
)


def test_to_decimal_trims_and_accepts_int():
    assert to_decimal(" 1.5 ") == Decimal("1.5")
    assert to_decimal(3) == Decimal(3)


@pytest.mark.parametrize("text", ["NaN", "Infinity", "-inf", "sNaN"])
def test_non_finite_rejected(text):
    with pytest.raises(EngineError) as exc:
        to_decimal(text)
    assert exc.value.code is ErrorCode.NON_FINITE_VALUE


def test_malformed_number_rejected():
    with pytest.raises(EngineError) as exc:
        to_decimal("1.2.3")
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT
    with pytest.raises(EngineError):
        to_decimal(object())


def test_rounding_without_uncertainty_uses_12_significant_digits():
    assert format_decimal(
        round_result(Decimal("1.23456789012345"), None)
    ) == "1.23456789012"
    assert format_decimal(round_result(Decimal("0"), None)) == "0"


def test_uncertainty_two_digits_when_leading_below_30():
    assert format_decimal(
        round_result(Decimal("1.23456"), Decimal("0.024"))
    ) == "1.235"
    assert format_decimal(round_uncertainty(Decimal("0.024"))) == "0.024"


def test_uncertainty_one_digit_when_leading_at_or_above_30():
    assert format_decimal(
        round_result(Decimal("1.23456"), Decimal("0.034"))
    ) == "1.23"
    assert format_decimal(round_uncertainty(Decimal("3.4"))) == "3"


def test_formatting_is_never_scientific():
    assert format_decimal(Decimal("0.000000000001")) == "0.000000000001"
