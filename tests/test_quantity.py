from decimal import Decimal

import pytest

from pqe.dimensions import DIMENSIONLESS, LENGTH, TIME
from pqe.errors import EngineError, ErrorCode
from pqe.numeric import engine_context
from pqe.quantity import PhysicalQuantity as Q


@pytest.fixture
def two_lengths():
    with engine_context():
        a = Q(Decimal("2.0"), LENGTH, Decimal("0.1"))
        b = Q(Decimal("3.0"), LENGTH, Decimal("0.2"))
    return a, b


def test_addition_requires_matching_dimension():
    with pytest.raises(EngineError) as exc:
        Q(Decimal(1), LENGTH).add(Q(Decimal(1), TIME))
    assert exc.value.code is ErrorCode.DIMENSION_MISMATCH


def test_addition_uncertainty_quadrature(two_lengths):
    a, b = two_lengths
    with engine_context():
        result = a.add(b)
        expected = (Decimal("0.1") ** 2 + Decimal("0.2") ** 2).sqrt()
    assert result.value == 5
    assert result.uncertainty == expected


def test_multiplication_dimensions_and_uncertainty():
    with engine_context():
        a = Q(Decimal("2"), DIMENSIONLESS, Decimal("0.2"))
        result = a.mul(Q.scalar(3))
    assert result.dimension.is_dimensionless()
    assert result.uncertainty == Decimal("0.6")
    assert Q(Decimal(2), LENGTH).mul(Q(Decimal(3), LENGTH)).dimension == LENGTH ** 2


def test_division_by_zero_rejected():
    with pytest.raises(EngineError) as exc:
        Q(Decimal(1), LENGTH).truediv(Q(Decimal(0), TIME))
    assert exc.value.code is ErrorCode.DIVISION_BY_ZERO


def test_trig_requires_dimensionless():
    with pytest.raises(EngineError) as exc:
        Q(Decimal(0), LENGTH).apply_unary("sin")
    assert exc.value.code is ErrorCode.DIMENSION_MISMATCH


def test_trig_values():
    with engine_context():
        assert Q.scalar(0).apply_unary("sin").value == 0
        assert abs(
            Q.scalar(0).apply_unary("cos").value - 1
        ) < Decimal("1e-40")
        pi = Decimal("3.1415926535897932384626433832795028")
        assert abs(
            Q.scalar(Decimal("0.5")).apply_unary("asin").value - pi / 6
        ) < Decimal("1e-30")


def test_exp_and_log_inverse():
    with engine_context():
        from pqe.quantity import _exp, _ln
        x = Decimal("1.2345")
        assert abs(_ln(_exp(x)) - x) < Decimal("1e-42")


def test_sqrt_keeps_dimension_when_exponents_even():
    area = Q(Decimal("4"), LENGTH ** 2)
    result = area.apply_unary("sqrt")
    assert result.value == 2
    assert result.dimension == LENGTH


def test_sqrt_rejects_odd_dimension_and_negative_value():
    with pytest.raises(EngineError) as exc:
        Q(Decimal("4"), LENGTH).apply_unary("sqrt")
    assert exc.value.code is ErrorCode.DIMENSION_MISMATCH
    with pytest.raises(EngineError) as exc:
        Q.scalar(-1).apply_unary("sqrt")
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT


def test_integer_power_and_dimensionless_power():
    with engine_context():
        assert Q(Decimal("2"), LENGTH).power_int(3).dimension == LENGTH ** 3
        value = Q.scalar(2).power_dimensionless(Q.scalar(3)).value
        assert abs(value - 8) < Decimal("1e-40")


def test_unknown_function_rejected():
    with pytest.raises(EngineError) as exc:
        Q.scalar(1).apply_unary("frobnicate")
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT


def test_exp_overflow_rejected_deterministically():
    with pytest.raises(EngineError) as exc:
        Q.scalar(Decimal("1e6000")).apply_unary("exp")
    assert exc.value.code is ErrorCode.OVERFLOW
