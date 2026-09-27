"""Cross-cutting checks: derived-unit conversions and determinism."""

import subprocess
import sys
from textwrap import dedent

import pytest

from pqengine.evaluator import evaluate
from pqengine.quantity import make_quantity
from pqengine.units import default_registry


@pytest.fixture
def reg():
    return default_registry()


def test_derived_unit_conversion_roundtrip(reg):
    # 1 kN expressed in N and back through compound m*kg/s^2.
    kn = make_quantity(1.0, "kN", 0.01, registry=reg)
    n = kn.to_unit("N", registry=reg)
    assert n.value == 1000.0
    assert n.uncertainty == pytest.approx(10.0)
    back = n.to_unit("kN", registry=reg)
    assert back.value == pytest.approx(1.0)
    assert back.uncertainty == pytest.approx(0.01)


def test_pressure_bar_pa_consistency(reg):
    q = make_quantity(2.5, "bar", 0.0, registry=reg)
    pa = q.to_unit("Pa", registry=reg)
    assert pa.value == 250000.0
    assert pa.unit.dimension == q.unit.dimension


def test_conversion_mismatch_has_no_partial_result(reg):
    q = make_quantity(1.0, "m", 0.1, registry=reg)
    with pytest.raises(Exception):  # noqa: B017 - any failure guarantees no output
        q.to_unit("kg", registry=reg)
    # Original quantity remains untouched.
    assert q.value == 1.0 and q.unit.name == "m" and q.uncertainty == 0.1


def test_conversion_preserves_uncertainty_ratio(reg):
    q = make_quantity(1000.0, "mm", 5.0, registry=reg)
    m = q.to_unit("m", registry=reg)
    assert m.value == pytest.approx(1.0)
    assert m.uncertainty == pytest.approx(0.005)


def test_energy_ev_joule(reg):
    q = make_quantity(1.0, "eV", registry=reg)
    j = q.to_unit("J", registry=reg)
    assert j.value == pytest.approx(1.602176634e-19)


def test_evaluated_result_is_frozen_and_complete(reg):
    vars_ = {"f": make_quantity(1.0, "kN", registry=reg),
             "d": make_quantity(2.0, "m", registry=reg)}
    r = evaluate("f * d", vars_, reg)
    # 1 kN * 2 m = 2000 J
    assert r.value == 2000.0
    assert r.unit.name == "J"
    with pytest.raises(AttributeError):
        r.value = 5.0  # type: ignore[misc]


def _subprocess_eval() -> str:
    code = dedent(
        """
        from pqengine.units import default_registry
        from pqengine.quantity import make_quantity
        from pqengine.evaluator import evaluate
        reg = default_registry()
        v = {
            "a": make_quantity(1.234567890123, "m", 0.0012, reg),
            "b": make_quantity(2.0, "m", 0.003, reg),
        }
        r = evaluate("(a / b)^2 + sqrt(16) * (a / b)", v, reg)
        print(f"{r.value!r}|{r.uncertainty!r}|{r.unit.name}")
        """
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def test_cross_process_determinism(reg):
    vars_ = {
        "a": make_quantity(1.234567890123, "m", 0.0012, reg),
        "b": make_quantity(2.0, "m", 0.003, reg),
    }
    r = evaluate("(a / b)^2 + sqrt(16) * (a / b)", vars_, reg)
    expected = f"{r.value!r}|{r.uncertainty!r}|{r.unit.name}"
    assert _subprocess_eval() == expected
