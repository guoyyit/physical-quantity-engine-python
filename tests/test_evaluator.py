
import pytest

from pqengine.errors import EngineError, ErrorCode
from pqengine.evaluator import evaluate
from pqengine.quantity import make_quantity
from pqengine.units import default_registry


@pytest.fixture
def reg():
    return default_registry()


def q(value, unit, u=0.0, reg=None):
    return make_quantity(value, unit, u, registry=reg)


def test_scalar_arithmetic(reg):
    assert evaluate("1 + 2", {}, reg).value == 3.0
    assert evaluate("4 * 2.5", {}, reg).value == 10.0
    assert evaluate("10 / 4", {}, reg).value == 2.5
    assert evaluate("2 - 5", {}, reg).value == -3.0
    assert evaluate("2^10", {}, reg).value == 1024.0


def test_named_variables_and_units(reg):
    vars_ = {
        "x": q(2.0, "m", 0.0, reg),
        "t": q(1.0, "s", 0.0, reg),
    }
    r = evaluate("x / t", vars_, reg)
    assert r.value == 2.0
    assert r.unit.dimension.matches(reg.resolve("m/s").dimension)


def test_addition_requires_matching_dimensions(reg):
    vars_ = {"x": q(1.0, "m", 0.0, reg), "t": q(1.0, "s", 0.0, reg)}
    with pytest.raises(EngineError) as exc:
        evaluate("x + t", vars_, reg)
    assert exc.value.code == ErrorCode.DIMENSION_MISMATCH


def test_subtraction_requires_matching_dimensions(reg):
    vars_ = {"x": q(1.0, "m", reg=reg), "t": q(1.0, "s", reg=reg)}
    with pytest.raises(EngineError) as exc:
        evaluate("x - t", vars_, reg)
    assert exc.value.code == ErrorCode.DIMENSION_MISMATCH


def test_addition_with_prefix_conversion(reg):
    vars_ = {"a": q(1.0, "m", 0.0, reg), "b": q(50.0, "cm", 0.0, reg)}
    r = evaluate("a + b", vars_, reg)
    assert r.value == pytest.approx(1.5)
    assert r.unit.name == "m"


def test_unknown_variable(reg):
    with pytest.raises(EngineError) as exc:
        evaluate("a + 1", {}, reg)
    assert exc.value.code == ErrorCode.UNKNOWN_QUANTITY


def test_division_by_zero(reg):
    with pytest.raises(EngineError) as exc:
        evaluate("1 / 0", {}, reg)
    assert exc.value.code == ErrorCode.DIVISION_BY_ZERO
    vars_ = {"x": q(0.0, "m", reg=reg)}
    with pytest.raises(EngineError) as exc:
        evaluate("1 / x", vars_, reg)
    assert exc.value.code == ErrorCode.DIVISION_BY_ZERO


def test_power_dimensions(reg):
    vars_ = {"x": q(2.0, "m", 0.0, reg)}
    r = evaluate("x^3", vars_, reg)
    assert r.value == 8.0
    assert r.unit.dimension.matches(reg.resolve("m^3").dimension)
    r = evaluate("x^-1", vars_, reg)
    assert r.value == 0.5
    assert r.unit.dimension.matches(reg.resolve("1/m").dimension)


def test_non_integer_exponent_rejected(reg):
    with pytest.raises(EngineError) as exc:
        evaluate("2^1.5", {}, reg)
    assert exc.value.code == ErrorCode.DIMENSION_MISMATCH


def test_unary_functions_dimensionless_only(reg):
    vars_ = {"x": q(2.0, "m", reg=reg)}
    with pytest.raises(EngineError) as exc:
        evaluate("sqrt(x)", vars_, reg)
    assert exc.value.code == ErrorCode.DIMENSION_MISMATCH


def test_unary_function_values(reg):
    assert evaluate("sqrt(16)", {}, reg).value == 4.0
    assert evaluate("sqr(3)", {}, reg).value == 9.0
    assert evaluate("abs(-7)", {}, reg).value == 7.0
    assert evaluate("ln(1)", {}, reg).value == pytest.approx(0.0, abs=1e-12)
    assert evaluate("log(1000)", {}, reg).value == pytest.approx(3.0, abs=1e-12)
    assert evaluate("exp(0)", {}, reg).value == 1.0
    assert evaluate("sin(0)", {}, reg).value == 0.0
    assert evaluate("cos(0)", {}, reg).value == 1.0
    assert evaluate("tan(0)", {}, reg).value == 0.0


def test_function_domain_errors(reg):
    with pytest.raises(EngineError) as exc:
        evaluate("sqrt(-1)", {}, reg)
    assert exc.value.code == ErrorCode.DOMAIN_ERROR
    with pytest.raises(EngineError) as exc:
        evaluate("ln(0)", {}, reg)
    assert exc.value.code == ErrorCode.DOMAIN_ERROR


def test_uncertainty_addition(reg):
    vars_ = {
        "a": q(10.0, "m", 0.1, reg),
        "b": q(20.0, "m", 0.2, reg),
    }
    r = evaluate("a + b", vars_, reg)
    assert r.value == 30.0
    # sqrt(0.05) = 0.2236... rounded to 2 significant figures -> 0.22
    assert r.uncertainty == pytest.approx(0.22, rel=1e-9)


def test_uncertainty_multiplication_relative(reg):
    vars_ = {
        "a": q(2.0, "m", 0.02, reg),   # 1%
        "b": q(3.0, "s", 0.03, reg),   # 1%
    }
    r = evaluate("a / b", vars_, reg)
    assert r.value == pytest.approx(0.6667, abs=1e-9)
    # 0.6667 * sqrt(2)*0.01 = 0.009428 -> 0.0094 (2 sig figs)
    assert r.uncertainty == pytest.approx(0.0094, rel=1e-9)


def test_uncertainty_unary(reg):
    vars_ = {"x": q(16.0, "1", 0.4, reg)}
    r = evaluate("sqrt(x)", vars_, reg)
    assert r.value == 4.0
    # u = 0.4 / 8 = 0.05
    assert r.uncertainty == pytest.approx(0.05, rel=1e-6)


def test_determinism_same_inputs(reg):
    vars_ = {"a": q(1.2345678901234, "m", 0.001, reg),
             "b": q(2.9876543219876, "m", 0.002, reg),
             "c": q(5.0, "m", 0.003, reg)}
    expr = "a * b + a * c"
    first = evaluate(expr, vars_, reg)
    for _ in range(5):
        again = evaluate(expr, vars_, reg)
        assert again == first


def test_uncertainty_power(reg):
    vars_ = {"x": q(2.0, "m", 0.01, reg)}
    r = evaluate("x^2", vars_, reg)
    assert r.value == 4.0
    assert r.uncertainty == pytest.approx(2 * 2.0 * 0.01, rel=1e-6)


def test_overflow_rejected(reg):
    with pytest.raises(EngineError) as exc:
        evaluate("1e200 * 1e200", {}, reg)
    assert exc.value.code == ErrorCode.OVERFLOW


def test_exp_overflow_rejected(reg):
    with pytest.raises(EngineError) as exc:
        evaluate("exp(1000)", {}, reg)
    assert exc.value.code == ErrorCode.OVERFLOW


def test_non_finite_input_variable_rejected(reg):
    from pqengine.quantity import Quantity
    with pytest.raises(EngineError) as exc:
        Quantity(float("nan"), reg.get("m"))
    assert exc.value.code == ErrorCode.NON_FINITE_VALUE


def test_zero_to_negative_power(reg):
    with pytest.raises(EngineError) as exc:
        evaluate("0^-1", {}, reg)
    assert exc.value.code == ErrorCode.DIVISION_BY_ZERO


def test_error_is_serializable(reg):
    try:
        evaluate("x", {}, reg)
    except EngineError as e:
        d = e.to_dict()
        assert d["code"] == "UNKNOWN_QUANTITY"
        assert isinstance(d["message"], str) and d["message"]
