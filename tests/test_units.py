import math

import pytest

from pqengine.dimensions import DIMENSIONLESS, LENGTH, MASS, TIME
from pqengine.errors import EngineError, ErrorCode
from pqengine.units import default_registry


@pytest.fixture
def reg():
    return default_registry()


def test_base_unit_roundtrip(reg):
    m = reg.get("m")
    assert m.to_si(2.0) == 2.0
    assert m.from_si(3.0) == 3.0


def test_prefixes(reg):
    km = reg.resolve("km")
    assert km.to_si(1.0) == 1000.0
    ms = reg.resolve("ms")
    assert ms.to_si(1.0) == 0.001
    assert ms.dimension.matches(TIME)


def test_derived_units(reg):
    n = reg.get("N")
    assert n.dimension.matches(LENGTH * MASS / TIME ** 2)
    pa = reg.get("Pa")
    assert n.to_si(1.0) == pytest.approx(pa.to_si(1.0) * 1.0)
    assert pa.from_si(1.0) == 1.0  # Pa is coherent with SI base units
    assert reg.get("bar").from_si(1e5) == 1.0  # 1 bar = 1e5 Pa


def test_accepted_units(reg):
    minute = reg.get("min")
    assert minute.to_si(2.0) == 120.0
    bar = reg.get("bar")
    assert bar.to_si(1.0) == 1e5
    deg = reg.get("deg")
    assert deg.to_si(180.0) == pytest.approx(math.pi)


def test_compound_units(reg):
    speed = reg.resolve("m/s")
    assert speed.dimension.matches(LENGTH / TIME)
    assert speed.to_si(1.0) == 1.0
    acc = reg.resolve("m/s^2")
    assert acc.dimension.matches(LENGTH / TIME ** 2)
    volume = reg.resolve("cm^3")
    assert volume.to_si(1.0) == pytest.approx(1e-6)
    weird = reg.resolve("kg*m/s^2")
    assert weird.dimension.matches(LENGTH * MASS / TIME ** 2)
    assert weird.to_si(1.0) == pytest.approx(1.0)
    kn = reg.resolve("kN")
    assert kn.dimension.matches(LENGTH * MASS / TIME ** 2)
    assert kn.to_si(1.0) == pytest.approx(1000.0)


def test_unknown_unit(reg):
    with pytest.raises(EngineError) as exc:
        reg.resolve("frobnicate")
    assert exc.value.code == ErrorCode.UNKNOWN_UNIT


def test_invalid_unit_expression(reg):
    with pytest.raises(EngineError) as exc:
        reg.resolve("m/")
    assert exc.value.code == ErrorCode.UNKNOWN_UNIT
    with pytest.raises(EngineError):
        reg.resolve("m^x")


def test_find_by_dimension(reg):
    assert reg.find_by_dimension(LENGTH / TIME) is None
    found = reg.find_by_dimension(MASS / (LENGTH * TIME ** 2))
    assert found is not None and found.name == "Pa"
    assert reg.find_by_dimension(DIMENSIONLESS).name == "one"
