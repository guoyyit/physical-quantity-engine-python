"""PhysicalQuantity: a Decimal value with dimension and optional standard uncertainty.

Values are always stored expressed in coherent SI base units, so dimension
checks are simple exponent comparisons. Input quantities are treated as
independent for uncertainty propagation (see docs/rules.md).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from math import gcd

from .dimensions import Dimension
from .errors import ErrorCode, EngineError
from .numeric import ONE, TWO, ZERO, engine_context


def _translate_decimal_error(exc: Exception, op: str) -> EngineError:
    """Map Decimal trap exceptions onto stable engine error codes."""
    name = type(exc).__name__
    if name in ("DivisionByZero", "DivisionUndefined", "DivisionImpossible"):
        return EngineError(ErrorCode.DIVISION_BY_ZERO, f"division by zero in {op}")
    if name == "Overflow":
        return EngineError(ErrorCode.OVERFLOW, f"numeric overflow in {op}")
    return EngineError(ErrorCode.INVALID_ARGUMENT, f"{name} in {op}: {exc}")


def _sqrt(value: Decimal) -> Decimal:
    # Decimal.sqrt uses the current context precision/rounding deterministically.
    return value.sqrt()


def _exp(x: Decimal) -> Decimal:
    # Range reduction: exp(x) = exp(n*ln2) * exp(r), r in [-ln2/2, ln2/2].
    ln2 = Decimal(
        "0.69314718055994530941723212145817656807550013436026"
    )
    n = (x / ln2).to_integral_value(rounding="ROUND_HALF_EVEN")
    r = x - n * ln2
    # Series for exp(r).
    total = ONE
    term = ONE
    k = 1
    while True:
        term = term * r / Decimal(k)
        total = total + term
        if term.is_zero() or abs(term) < _series_tolerance():
            break
        k += 1
    return Decimal(2) ** int(n) * total


def _series_tolerance() -> Decimal:
    from .numeric import CONTEXT_PRECISION

    return Decimal(1).scaleb(-(CONTEXT_PRECISION - 6))


def _ln(x: Decimal) -> Decimal:
    if x <= 0:
        raise EngineError(
            ErrorCode.INVALID_ARGUMENT, f"ln is undefined for value {x}")
    # Compute ln(x) via atanh series after extracting power-of-2 exponent:
    # x = m * 2^e, m in [1, 2); y = (m-1)/(m+1), ln(m) = 2*sum y^(2k+1)/(2k+1).
    e = x.adjusted()
    m = x / Decimal(2) ** e
    y = (m - ONE) / (m + ONE)
    y2 = y * y
    total = ZERO
    term = y
    k = 1
    while True:
        add = term / Decimal(k)
        total = total + add
        if abs(add) < _series_tolerance():
            break
        term = term * y2
        k += 2
    ln2 = Decimal(
        "0.69314718055994530941723212145817656807550013436026"
    )
    return TWO * total + Decimal(e) * ln2


def _sin(x: Decimal) -> Decimal:
    pi = _PI
    # Reduce to [-pi, pi].
    two_pi = TWO * pi
    n = (x / two_pi).to_integral_value(rounding="ROUND_HALF_EVEN")
    x = x - n * two_pi
    total = ZERO
    term = x
    k = 1
    while True:
        total = total + term
        next_term = -term * x * x / (Decimal((k + 1) * (k + 2)))
        if abs(next_term) < _series_tolerance():
            break
        term = next_term
        k += 2
    return total


def _cos(x: Decimal) -> Decimal:
    pi = _PI
    two_pi = TWO * pi
    n = (x / two_pi).to_integral_value(rounding="ROUND_HALF_EVEN")
    x = x - n * two_pi
    total = ONE
    term = ONE
    k = 0
    while True:
        next_term = -term * x * x / (Decimal((k + 1) * (k + 2)))
        total = total + next_term
        if abs(next_term) < _series_tolerance():
            break
        term = next_term
        k += 2
    return total


def _tan(x: Decimal) -> Decimal:
    c = _cos(x)
    if c == 0:
        raise EngineError(
            ErrorCode.INVALID_ARGUMENT, "tan is undefined at this angle")
    return _sin(x) / c


def _asin(x: Decimal) -> Decimal:
    if x < -ONE or x > ONE:
        raise EngineError(
            ErrorCode.INVALID_ARGUMENT, f"asin argument {x} outside [-1, 1]")
    return _atan2(x, _sqrt(ONE - x * x)) if x != ONE else _PI / TWO


def _acos(x: Decimal) -> Decimal:
    if x < -ONE or x > ONE:
        raise EngineError(
            ErrorCode.INVALID_ARGUMENT, f"acos argument {x} outside [-1, 1]")
    return _PI / TWO - _asin(x)


def _atan(x: Decimal) -> Decimal:
    return _atan2(x, ONE)


def _atan2(y: Decimal, x: Decimal) -> Decimal:
    # atan(y/x) for x > 0 via argument reduction with tan(pi/4).
    pi = _PI
    if x == 0:
        if y == 0:
            return ZERO
        return pi / TWO if y > 0 else -pi / TWO
    ratio = y / x
    if abs(ratio) > ONE:
        # atan(r) = pi/2 - atan(1/r) for r > 1.
        base = pi / TWO if ratio > 0 else -pi / TWO
        z = ONE / ratio
    else:
        base = ZERO
        z = ratio
    a = Decimal("0.267949192431122706472553658494127633471013795")  # tan(pi/12)
    angle = pi / Decimal(12)
    # Reduce |z| into [-tan(pi/12), tan(pi/12)].
    quadrant = 0
    if z > a:
        z = (z - a) / (ONE + a * z)
        quadrant = 1
    elif z < -a:
        z = (z + a) / (ONE - a * z)
        quadrant = -1
    z2 = z * z
    total = z
    term = z
    k = 3
    while True:
        term = term * z2
        add = term / Decimal(k)
        total = total - add
        term = term * z2
        k += 2
        add2 = term / Decimal(k)
        total = total + add2
        if abs(add2) < _series_tolerance():
            break
        k += 2
    return base + total + quadrant * angle


_PI = Decimal("3.14159265358979323846264338327950288419716939937510")
_E = Decimal("2.71828182845904523536028747135266249775724709369995")


def constants() -> dict[str, "PhysicalQuantity"]:
    """Built-in dimensionless constants available in expressions."""
    return {
        "pi": PhysicalQuantity.scalar(_PI),
        "e": PhysicalQuantity.scalar(_E),
    }


@dataclass(frozen=True)
class PhysicalQuantity:
    """Value stored expressed in coherent SI base units."""

    value: Decimal
    dimension: Dimension
    uncertainty: Decimal | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.value, Decimal):
            object.__setattr__(self, "value", Decimal(self.value))
        if self.uncertainty is not None and not isinstance(
                self.uncertainty, Decimal):
            object.__setattr__(self, "uncertainty", Decimal(self.uncertainty))

    @classmethod
    def scalar(cls, value: Decimal) -> "PhysicalQuantity":
        return cls(value, Dimension.scalar(), None)

    def require_dimensionless(self, op: str) -> None:
        if not self.dimension.is_dimensionless():
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"{op} requires a dimensionless argument, got "
                f"{self.dimension.format()}",
            )

    def require_same_dimension(self, other: "PhysicalQuantity", op: str) -> None:
        if not self.dimension.compatible_with(other.dimension):
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"{op}: dimensions {self.dimension.format()} and "
                f"{other.dimension.format()} are incompatible",
            )

    def _u(self) -> Decimal:
        return self.uncertainty if self.uncertainty is not None else ZERO

    # -- arithmetic -------------------------------------------------------
    def add(self, other: "PhysicalQuantity") -> "PhysicalQuantity":
        self.require_same_dimension(other, "addition")
        try:
            with engine_context():
                value = self.value + other.value
        except Exception as exc:  # Decimal traps
            raise _translate_decimal_error(exc, "addition")
        uncertainty = _combine_uncertainties(self._u(), other._u())
        return PhysicalQuantity(value, self.dimension, uncertainty)

    def sub(self, other: "PhysicalQuantity") -> "PhysicalQuantity":
        self.require_same_dimension(other, "subtraction")
        try:
            with engine_context():
                value = self.value - other.value
        except Exception as exc:
            raise _translate_decimal_error(exc, "subtraction")
        uncertainty = _combine_uncertainties(self._u(), other._u())
        return PhysicalQuantity(value, self.dimension, uncertainty)

    def mul(self, other: "PhysicalQuantity") -> "PhysicalQuantity":
        try:
            with engine_context():
                value = self.value * other.value
        except Exception as exc:
            raise _translate_decimal_error(exc, "multiplication")
        uncertainty = None
        if self.uncertainty is not None or other.uncertainty is not None:
            with engine_context():
                a = (self._u() * other.value) ** 2
                b = (self.value * other._u()) ** 2
                uncertainty = _sqrt(a + b)
        return PhysicalQuantity(value, self.dimension * other.dimension,
                                uncertainty)

    def truediv(self, other: "PhysicalQuantity") -> "PhysicalQuantity":
        try:
            with engine_context():
                if other.value == 0:
                    raise EngineError(
                        ErrorCode.DIVISION_BY_ZERO,
                        "division by a quantity whose value is zero")
                value = self.value / other.value
        except EngineError:
            raise
        except Exception as exc:
            raise _translate_decimal_error(exc, "division")
        uncertainty = None
        if self.uncertainty is not None or other.uncertainty is not None:
            with engine_context():
                ov = other.value
                a = self._u() / ov
                b = self.value * other._u() / (ov * ov)
                uncertainty = _sqrt((a ** 2) + (b ** 2))
        return PhysicalQuantity(value, self.dimension / other.dimension,
                                uncertainty)

    def neg(self) -> "PhysicalQuantity":
        return PhysicalQuantity(-self.value, self.dimension, self.uncertainty)

    def pos(self) -> "PhysicalQuantity":
        return self

    def power_int(self, n: int) -> "PhysicalQuantity":
        """Raise to an integer power (dimensions may scale arbitrarily)."""
        if not isinstance(n, int) or isinstance(n, bool):
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT, "exponent must be an integer")
        try:
            with engine_context():
                value = self.value ** n
        except Exception as exc:
            raise _translate_decimal_error(exc, "power")
        uncertainty = None
        if self.uncertainty is not None:
            if self.value == 0 and n > 1:
                uncertainty = ZERO
            else:
                with engine_context():
                    uncertainty = abs(
                        Decimal(n) * self.value ** (n - 1) * self._u())
        return PhysicalQuantity(value, self.dimension ** n, uncertainty)

    def power_dimensionless(self, q: "PhysicalQuantity") -> "PhysicalQuantity":
        """Raise to a dimensionless numeric power (base must be dimensionless)."""
        q.require_dimensionless("power")
        self.require_dimensionless("power")
        exponent = q.value
        try:
            with engine_context():
                if self.value <= 0:
                    raise EngineError(
                        ErrorCode.INVALID_ARGUMENT,
                        f"non-positive base {self.value} for real power")
                value = _exp(exponent * _ln(self.value))
        except EngineError:
            raise
        except Exception as exc:
            raise _translate_decimal_error(exc, "power")
        uncertainty = None
        if self.uncertainty is not None or q.uncertainty is not None:
            with engine_context():
                dv = abs(exponent * value * self._u() / self.value)
                de = abs(value * _ln(self.value) * q._u())
                uncertainty = _sqrt(dv * dv + de * de)
        return PhysicalQuantity(value, Dimension.scalar(), uncertainty)

    # -- unary functions --------------------------------------------------
    def apply_unary(self, name: str) -> "PhysicalQuantity":
        fn = _UNARY_FUNCTIONS.get(name)
        if fn is None:
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT, f"unknown function: {name}")
        return fn(self)


def _combine_uncertainties(a: Decimal, b: Decimal) -> Decimal | None:
    if a == 0 and b == 0:
        return ZERO
    with engine_context():
        return _sqrt(a * a + b * b)


def _require_dimensionless(q: PhysicalQuantity, name: str) -> None:
    q.require_dimensionless(f"function {name}")


def _make_unary(name: str, dimensionless: bool, fn,
                uncertainty_fn=None) -> "function":
    def wrapped(q: PhysicalQuantity) -> PhysicalQuantity:
        if dimensionless:
            _require_dimensionless(q, name)
        try:
            with engine_context():
                value = fn(q.value)
        except EngineError:
            raise
        except Exception as exc:
            raise _translate_decimal_error(exc, name)
        uncertainty = None
        if q.uncertainty is not None:
            with engine_context():
                if uncertainty_fn is None:
                    uncertainty = ZERO
                else:
                    uncertainty = abs(uncertainty_fn(q.value) * q._u())
        return PhysicalQuantity(value, Dimension.scalar(), uncertainty)

    wrapped.__name__ = f"fn_{name}"
    return wrapped


def _sqrt_unary(q: PhysicalQuantity) -> PhysicalQuantity:
    # sqrt accepts any dimension; result dimension exponents must stay integer.
    for e in q.dimension.exponents:
        if e % 2 != 0:
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"sqrt requires even dimension exponents, got "
                f"{q.dimension.format()}",
            )
    if q.value < 0:
        raise EngineError(
            ErrorCode.INVALID_ARGUMENT, f"sqrt of negative value {q.value}")
    with engine_context():
        value = _sqrt(q.value)
        uncertainty = None
        if q.uncertainty is not None and q.value != 0:
            uncertainty = q._u() / (TWO * value)
    new_dim = Dimension(tuple(e // 2 for e in q.dimension.exponents))
    return PhysicalQuantity(value, new_dim, uncertainty)


def _abs_unary(q: PhysicalQuantity) -> PhysicalQuantity:
    return PhysicalQuantity(abs(q.value), q.dimension, q.uncertainty)


_UNARY_FUNCTIONS: dict[str, object] = {
    "sqrt": _sqrt_unary,
    "abs": _abs_unary,
    "sin": _make_unary("sin", True, _sin, _cos),
    "cos": _make_unary("cos", True, _cos, lambda x: -_sin(x)),
    "tan": _make_unary("tan", True, _tan,
                       lambda x: ONE + _tan(x) * _tan(x)),
    "asin": _make_unary("asin", True, _asin,
                        lambda x: ONE / _sqrt(ONE - x * x)),
    "acos": _make_unary("acos", True, _acos,
                        lambda x: -ONE / _sqrt(ONE - x * x)),
    "atan": _make_unary("atan", True, _atan,
                        lambda x: ONE / (ONE + x * x)),
    "exp": _make_unary("exp", True, _exp, _exp),
    "ln": _make_unary("ln", True, _ln, lambda x: ONE / x),
    "log10": _make_unary("log10", True,
                         lambda x: _ln(x) / _ln(Decimal(10)),
                         lambda x: ONE / (x * _ln(Decimal(10)))),
    "log2": _make_unary("log2", True,
                        lambda x: _ln(x) / _ln(TWO),
                        lambda x: ONE / (x * _ln(TWO))),
}
