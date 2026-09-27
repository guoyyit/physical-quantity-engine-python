from decimal import Decimal

import pytest

from pqe.errors import EngineError, ErrorCode


def test_arithmetic_against_catalog(seeded_evaluator):
    result = seeded_evaluator.evaluate("2 + 3 * 4")
    assert result.value_text == "14.0000000000"
    assert result.dimension == (0, 0, 0, 0, 0, 0, 0)


def test_dimension_vector_and_default_unit(seeded_evaluator):
    result = seeded_evaluator.evaluate("distance / elapsed")
    assert result.dimension == (1, 0, -1, 0, 0, 0, 0)
    assert result.unit == "m*s^-1"


def test_output_unit_conversion(seeded_evaluator):
    result = seeded_evaluator.evaluate(
        "distance / elapsed", output_unit="km/h")
    assert result.unit == "km/h"
    assert result.value_text == "50.0000000000"


def test_dimension_mismatch_is_distinct(seeded_evaluator):
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.evaluate("distance + elapsed")
    assert exc.value.code is ErrorCode.DIMENSION_MISMATCH
    assert "L" in exc.value.message and "T" in exc.value.message


def test_output_unit_dimension_mismatch(seeded_evaluator):
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.evaluate("distance", output_unit="s")
    assert exc.value.code is ErrorCode.DIMENSION_MISMATCH


def test_unknown_name_distinct_from_parse_error(seeded_evaluator):
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.evaluate("missing + 1")
    assert exc.value.code is ErrorCode.UNKNOWN_NAME
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.evaluate("1 +")
    assert exc.value.code is ErrorCode.PARSE_ERROR


def test_uncertainty_propagation_through_multiplication(seeded_evaluator):
    result = seeded_evaluator.evaluate("accel * 2")
    # u = 2 * 0.1 = 0.2 (one sig digit), value aligned to tenths.
    assert result.uncertainty_text == "0.20"
    assert result.value_text == "19.60"


def test_results_are_deterministic(seeded_evaluator):
    first = seeded_evaluator.evaluate(
        "distance/elapsed", output_unit="m/s").to_dict()
    second = seeded_evaluator.evaluate(
        "distance/elapsed", output_unit="m/s").to_dict()
    assert first == second


def test_version_pinning_isolates_later_commits(catalog, units):
    from pqe.evaluator import Evaluator
    evaluator = Evaluator(catalog, units)
    v1 = catalog.add("x", "1", "m").version
    evaluator.evaluate("x", version=v1)
    catalog.add("y", "2", "m")
    with pytest.raises(EngineError) as exc:
        evaluator.evaluate("y", version=v1)
    assert exc.value.code is ErrorCode.UNKNOWN_NAME


def test_missing_version_rejected(seeded_evaluator):
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.evaluate("1", version=999)
    assert exc.value.code is ErrorCode.VERSION_NOT_FOUND


def test_constants_and_functions(seeded_evaluator):
    result = seeded_evaluator.evaluate("sin(pi/2)")
    assert result.value_text.startswith("1.00000000000")
    assert seeded_evaluator.evaluate("e^0").value_text.startswith(
        "1.00000000000")


def test_division_by_zero(seeded_evaluator):
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.evaluate("1 / 0")
    assert exc.value.code is ErrorCode.DIVISION_BY_ZERO


def test_convert_api_happy_path(seeded_evaluator):
    out = seeded_evaluator.convert("100", "km/h", "m/s")
    assert out["value"] == "27.7777777778"
    assert out["unit"] == "m/s"


def test_convert_with_uncertainty(seeded_evaluator):
    out = seeded_evaluator.convert("100", "km", "m", uncertainty="2")
    assert out["value"] == "100000"
    assert out["uncertainty"] == "2000"


def test_convert_dimension_mismatch_explained(seeded_evaluator):
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.convert("1", "m", "s")
    assert exc.value.code is ErrorCode.DIMENSION_MISMATCH


def test_convert_celsius_round_trip(seeded_evaluator):
    assert seeded_evaluator.convert("0", "degC", "K")["value"] == \
        "273.150000000"
    assert seeded_evaluator.convert("373.15", "K", "degC")["value"] == \
        "100.000000000"


def test_convert_negative_uncertainty_rejected(seeded_evaluator):
    with pytest.raises(EngineError) as exc:
        seeded_evaluator.convert("1", "m", "km", uncertainty="-1")
    assert exc.value.code is ErrorCode.INVALID_ARGUMENT
