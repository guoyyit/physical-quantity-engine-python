import pytest

from pqe.dimensions import (
    AMOUNT,
    CURRENT,
    DIMENSIONLESS,
    LENGTH,
    LUMINOUS_INTENSITY,
    MASS,
    TEMPERATURE,
    TIME,
    Dimension,
)


def test_scalar_dimension():
    assert Dimension.scalar().is_dimensionless()
    assert DIMENSIONLESS.format() == "1"


def test_arithmetic_and_format():
    velocity = LENGTH / TIME
    assert velocity.format() == "L*T^-1"
    assert (LENGTH ** 2).format() == "L^2"
    assert (velocity * TIME).compatible_with(LENGTH)
    assert (LENGTH / LENGTH).is_dimensionless()


def test_compatibility():
    assert LENGTH.compatible_with(LENGTH)
    assert not LENGTH.compatible_with(MASS)
    assert MASS.compatible_with(MASS)
    assert CURRENT.format() == "I"
    assert TEMPERATURE.format() == "Θ"
    assert AMOUNT.format() == "N"
    assert LUMINOUS_INTENSITY.format() == "J"


def test_power_scales_all_exponents():
    force = MASS * LENGTH / (TIME ** 2)
    assert force.format() == "L*M*T^-2"
    assert (force ** 0).is_dimensionless()


def test_invalid_vector_rejected():
    with pytest.raises(ValueError):
        Dimension((1, 0, 0))
    with pytest.raises(ValueError):
        Dimension((1.0, 0, 0, 0, 0, 0, 0))


def test_power_requires_integer():
    with pytest.raises(TypeError):
        LENGTH ** 1.5
