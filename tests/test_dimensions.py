import pytest

from pqengine.dimensions import (
    DIMENSIONLESS,
    LENGTH,
    MASS,
    TIME,
    Dimension,
)


def test_base_dimensions_distinct():
    assert LENGTH.matches(LENGTH)
    assert not LENGTH.matches(MASS)
    assert DIMENSIONLESS.is_dimensionless()


def test_multiply_and_divide():
    speed = LENGTH / TIME
    assert str(speed) == "length·time^-1"
    area = LENGTH * LENGTH
    assert area == LENGTH ** 2
    assert (speed * TIME).matches(LENGTH)


def test_power():
    assert (LENGTH ** 3).exponents[0] == 3
    assert (LENGTH ** 0).is_dimensionless()
    with pytest.raises(TypeError):
        LENGTH ** 1.5  # type: ignore[misc]


def test_bad_vector_length():
    with pytest.raises(ValueError):
        Dimension((1, 2))
