from decimal import Decimal

import pytest

from pqe.errors import EngineError, ErrorCode


def test_base_and_prefix_scaling(units):
    assert units.lookup("m").scale == 1
    assert units.lookup("km").to_base(Decimal(3)) == 3000
    assert units.lookup("kg").scale == 1
    assert units.lookup("mg").scale == Decimal("0.000001")
    assert units.lookup("MHz").scale == Decimal("1e6")
    assert units.lookup("kN").scale == 1000


def test_derived_units_dimensions(units):
    newton = units.lookup("N")
    assert newton.dimension.format() == "L*M*T^-2"
    assert units.lookup("Pa").dimension.format() == "L^-1*M*T^-2"
    assert units.lookup("J").dimension.format() == "L^2*M*T^-2"
    assert units.lookup("W").dimension.format() == "L^2*M*T^-3"
    ohm = units.lookup("Ohm")
    assert ohm.dimension.format() == "L^2*M*T^-3*I^-2"


def test_compound_parsing_and_scaling(units):
    speed = units.parse("km/h")
    assert speed.dimension.format() == "L*T^-1"
    assert speed.scale == Decimal(1000) / Decimal(3600)
    acc = units.parse("m/s^2")
    assert acc.dimension.format() == "L*T^-2"
    assert acc.scale == 1
    density = units.parse("kg/m^3")
    assert density.dimension.format() == "L^-3*M"


def test_accepted_non_si_units(units):
    assert units.lookup("h").to_base(Decimal(1)) == 3600
    assert units.parse("L").to_base(Decimal(1)) == Decimal("0.001")
    assert units.parse("mL").to_base(Decimal(1)) == Decimal("0.000001")
    assert units.lookup("t").to_base(Decimal(1)) == 1000
    assert units.lookup("eV").scale == Decimal("1.602176634e-19")


def test_celsius_offset_round_trip(units):
    celsius = units.lookup("degC")
    assert celsius.to_base(Decimal("0")) == Decimal("273.15")
    assert celsius.from_base(Decimal("373.15")) == Decimal("100")


def test_offset_unit_forbidden_in_compound(units):
    with pytest.raises(EngineError) as exc:
        units.parse("degC/s")
    assert exc.value.code is ErrorCode.UNIT_CONVERSION_FAILED


@pytest.mark.parametrize("text", [
    "foo", "", "m/", "/m", "m*", "m^^2", "2m", "degC*s", "m**2",
])
def test_invalid_units(units, text):
    with pytest.raises(EngineError) as exc:
        units.parse(text)
    assert exc.value.code in (
        ErrorCode.UNKNOWN_UNIT, ErrorCode.UNIT_CONVERSION_FAILED)
