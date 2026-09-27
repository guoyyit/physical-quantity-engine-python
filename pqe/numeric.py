"""Fixed-precision decimal arithmetic settings and deterministic rounding.

Determinism rules (see docs/rules.md):

* internal arithmetic uses Decimal precision 50, rounding ROUND_HALF_EVEN;
* DivisionByZero / InvalidOperation / Overflow trap and become EngineError;
* quantities without uncertainty are rounded to 12 significant digits;
* uncertainties use the standard GUM convention of 1 significant digit when
  the first two significant digits are 30..99, otherwise 2 significant digits,
  and the value is rounded to the same decimal place.
"""
from __future__ import annotations

from contextlib import contextmanager
from decimal import (
    Context,
    Decimal,
    DivisionByZero,
    InvalidOperation,
    Overflow,
    ROUND_HALF_EVEN,
    localcontext,
)

from .errors import ErrorCode, EngineError

# Internal working precision and rounding: fixed for full determinism.
CONTEXT_PRECISION = 50
RESULT_SIGNIFICANT_DIGITS = 12
# Upper bound on uncertainty leading digits that keeps 2 significant digits.
UNCERTAINTY_TWO_DIGIT_LIMIT = 29

ZERO = Decimal(0)
ONE = Decimal(1)
TWO = Decimal(2)

_TRAPS = (DivisionByZero, InvalidOperation, Overflow)

_engine_ctx = Context(
    prec=CONTEXT_PRECISION,
    rounding=ROUND_HALF_EVEN,
)
for _signal in _TRAPS:
    _engine_ctx.traps[_signal] = True


@contextmanager
def engine_context():
    """Run arithmetic under the fixed engine Decimal context."""
    with localcontext(_engine_ctx):
        yield


def to_decimal(text) -> Decimal:
    """Parse a finite decimal from a string; never accepts inf/NaN."""
    if isinstance(text, Decimal):
        value = text
    elif isinstance(text, bool):
        raise EngineError(ErrorCode.INVALID_ARGUMENT, "boolean is not a number")
    elif isinstance(text, int):
        value = Decimal(text)
    else:
        try:
            value = Decimal(str(text).strip())
        except (InvalidOperation, ValueError):
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT, f"not a valid decimal number: {text!r}"
            )
    if not value.is_finite():
        raise EngineError(
            ErrorCode.NON_FINITE_VALUE, f"non-finite number is not accepted: {text!r}"
        )
    return value


def _round_significant(value: Decimal, digits: int) -> Decimal:
    if value == 0:
        return ZERO
    quantum = ONE.scaleb(value.adjusted() - digits + 1)
    return value.quantize(quantum, rounding=ROUND_HALF_EVEN)


def round_result(value: Decimal, uncertainty: Decimal | None) -> Decimal:
    """Deterministically round *value* according to its uncertainty."""
    if uncertainty is None or uncertainty == 0:
        return _round_significant(value, RESULT_SIGNIFICANT_DIGITS)
    u = abs(uncertainty)
    # First two significant digits as an integer, e.g. 0.0234 -> 23, 345 -> 34.
    leading = int(u * (ONE.scaleb(1 - u.adjusted())))
    digits = 2 if leading <= UNCERTAINTY_TWO_DIGIT_LIMIT else 1
    u_rounded = _round_significant(u, digits)
    if u_rounded == 0:
        # Rounding collapsed the uncertainty; keep one guard digit of precision.
        u_rounded = u
    try:
        return value.quantize(u_rounded, rounding=ROUND_HALF_EVEN)
    except Exception:
        # The uncertainty's decimal place is finer than the working
        # precision can align to; present the value at the standard
        # significant-digit rule instead of raising.
        return _round_significant(value, RESULT_SIGNIFICANT_DIGITS)


def round_uncertainty(uncertainty: Decimal) -> Decimal:
    """Round an uncertainty with the same GUM rule used for values."""
    u = abs(uncertainty)
    if u == 0:
        return ZERO
    leading = int(u * (ONE.scaleb(1 - u.adjusted())))
    digits = 2 if leading <= UNCERTAINTY_TWO_DIGIT_LIMIT else 1
    return _round_significant(u, digits)


def format_decimal(value: Decimal) -> str:
    """Fixed-point (never scientific), deterministic decimal text."""
    text = format(value, "f")
    return text
