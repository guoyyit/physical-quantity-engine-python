import pytest

from pqengine.errors import EngineError, ErrorCode
from pqengine.quantity import Quantity, make_quantity
from pqengine.units import default_registry


@pytest.fixture
def reg():
    return default_registry()


def test_basic_construction(reg):
    q = make_quantity(1.0, "m", 0.01, registry=reg)
    assert q.si_value == 1.0
    assert q.si_uncertainty == 0.01


def test_convert_prefix(reg):
    q = make_quantity(2.0, "km", 0.1, registry=reg)
    m = q.to_unit("m", registry=reg)
    assert m.value == 2000.0
    assert m.uncertainty == pytest.approx(100.0)


def test_convert_derived(reg):
    q = make_quantity(1.0, "bar", 0.0, registry=reg)
    pa = q.to_unit("Pa", registry=reg)
    assert pa.value == 1e5
    hour = make_quantity(1.0, "h", registry=reg)
    assert hour.to_unit("s", registry=reg).value == 3600.0


def test_convert_dimension_mismatch(reg):
    q = make_quantity(1.0, "m", registry=reg)
    with pytest.raises(EngineError) as exc:
        q.to_unit("s", registry=reg)
    assert exc.value.code == ErrorCode.UNIT_CONVERSION_FAILED


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
def test_non_finite_value_rejected(reg, bad):
    with pytest.raises(EngineError) as exc:
        Quantity(bad, reg.get("m"))
    assert exc.value.code == ErrorCode.NON_FINITE_VALUE


def test_non_finite_uncertainty_rejected(reg):
    with pytest.raises(EngineError) as exc:
        Quantity(1.0, reg.get("m"), float("nan"))
    assert exc.value.code == ErrorCode.NON_FINITE_VALUE


def test_negative_uncertainty_rejected(reg):
    with pytest.raises(EngineError) as exc:
        Quantity(1.0, reg.get("m"), -0.1)
    assert exc.value.code == ErrorCode.UNCERTAINTY_INVALID


def test_unknown_unit_in_factory(reg):
    with pytest.raises(EngineError) as exc:
        make_quantity(1.0, "zzz", registry=reg)
    assert exc.value.code == ErrorCode.UNKNOWN_UNIT
