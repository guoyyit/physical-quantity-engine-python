"""Expression evaluation with dimensional checks and uncertainty propagation.

All arithmetic is performed in SI base units using :class:`decimal.Decimal`
with a fixed precision and HALF_UP rounding, so identical inputs always
produce identical results.  Values are reported to :data:`VALUE_SIG_FIGS`
significant figures; standard uncertainties to
:data:`UNCERTAINTY_SIG_FIGS` significant figures, and the reported value is
aligned to the uncertainty's decimal place when an uncertainty is present.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from decimal import Decimal, InvalidOperation, getcontext, localcontext

from .dimensions import DIMENSIONLESS
from .errors import EngineError, ErrorCode
from .parser import Binary, Name, Node, Number, Unary, parse
from .quantity import Quantity
from .units import Unit, UnitRegistry, default_registry

# Fixed, deterministic numerical policy.
DECIMAL_PRECISION = 40
VALUE_SIG_FIGS = 10
UNCERTAINTY_SIG_FIGS = 2
_OVERFLOW = Decimal("1e308")


def _ctx():
    ctx = getcontext().copy()
    ctx.prec = DECIMAL_PRECISION
    return ctx


def _dec(number: float) -> Decimal:
    if not math.isfinite(number):
        raise EngineError(
            ErrorCode.NON_FINITE_VALUE, f"non-finite number: {number!r}"
        )
    return Decimal(str(number))


def _quantize_sig(value: Decimal, sig_figs: int) -> Decimal:
    if value == 0:
        return Decimal(0)
    clamped = abs(value)
    # Position of the most significant digit.
    magnitude = clamped.adjusted()  # floor(log10(abs(value)))
    exponent = magnitude - (sig_figs - 1)
    quantum = Decimal(1).scaleb(exponent)
    return value.quantize(quantum, rounding="ROUND_HALF_UP")


def _align(value: Decimal, uncertainty: Decimal) -> Decimal:
    if uncertainty == 0:
        return value
    # Round value to the uncertainty's least significant decimal place.
    exponent = uncertainty.as_tuple().exponent
    quantum = Decimal(1).scaleb(exponent)
    return value.quantize(quantum, rounding="ROUND_HALF_UP")


def _check_overflow(value: Decimal, what: str) -> None:
    if abs(value) > _OVERFLOW:
        raise EngineError(
            ErrorCode.OVERFLOW, f"{what} overflow: magnitude exceeds 1e308"
        )


def _to_float(value: Decimal, what: str) -> float:
    _check_overflow(value, what)
    try:
        return float(value)
    except (OverflowError, InvalidOperation):
        raise EngineError(ErrorCode.OVERFLOW, f"{what} overflow") from None


class Evaluator:
    def __init__(
        self,
        variables: dict[str, Quantity],
        registry: UnitRegistry | None = None,
    ) -> None:
        self._variables = variables
        self._registry = registry if registry is not None else default_registry()

    # -- public API ------------------------------------------------------

    def evaluate_expression(self, expression: str) -> Quantity:
        return self.eval(parse(expression))

    def eval(self, node: Node) -> Quantity:
        with localcontext(self._ctx()):
            quantity = self._eval(node)
        return self._report(quantity)

    def _ctx(self):
        return _ctx()

    # -- internal --------------------------------------------------------

    def _report(self, q: Quantity) -> Quantity:
        v = _dec(q.value)
        u = _dec(q.uncertainty)
        if u > 0:
            u_r = _quantize_sig(u, UNCERTAINTY_SIG_FIGS)
            v_r = _align(v, u_r)
        else:
            u_r = Decimal(0)
            v_r = _quantize_sig(v, VALUE_SIG_FIGS)
        return Quantity(_to_float(v_r, "value"), q.unit,
                        _to_float(u_r, "uncertainty"))

    def _eval(self, node: Node) -> Quantity:
        if isinstance(node, Number):
            return Quantity(float(node.value), self._one_unit(), 0.0)
        if isinstance(node, Name):
            if node.name not in self._variables:
                raise EngineError(
                    ErrorCode.UNKNOWN_QUANTITY,
                    f"unknown quantity: {node.name!r}",
                )
            return self._variables[node.name]
        if isinstance(node, Unary):
            return self._eval_unary(node)
        return self._eval_binary(node)

    # -- unary -----------------------------------------------------------

    def _eval_unary(self, node: Unary) -> Quantity:
        if node.op in ("neg", "pos"):
            q = self._eval(node.operand)
            return Quantity(
                -q.value if node.op == "neg" else q.value, q.unit, q.uncertainty
            )
        arg = self._eval(node.operand)
        if not arg.unit.dimension.is_dimensionless():
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"function {node.op!r} requires a dimensionless argument, "
                f"got {arg.unit.dimension}",
            )
        x = _dec(arg.value)
        u = _dec(arg.uncertainty)
        fx, df = _UNARY[node.op](x)
        ux = abs(df) * u
        _check_overflow(fx, node.op)
        return Quantity(_to_float(fx, node.op), self._one_unit(),
                        _to_float(ux, "uncertainty"))

    # -- binary ----------------------------------------------------------

    def _eval_binary(self, node: Binary) -> Quantity:
        if node.op == "^":
            return self._eval_power(node)
        left = self._eval(node.left)
        right = self._eval(node.right)
        if node.op in ("+", "-"):
            return self._add_sub(node.op, left, right)
        return self._mul_div(node.op, left, right)

    def _add_sub(self, op: str, left: Quantity, right: Quantity) -> Quantity:
        if not left.unit.dimension.matches(right.unit.dimension):
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"cannot { 'subtract' if op == '-' else 'add'} "
                f"{left.unit.dimension} and {right.unit.dimension}",
            )
        # Evaluate both in the left operand's unit for deterministic output.
        rv = right.to_unit(left.unit, self._registry)
        a, b = _dec(left.value), _dec(rv.value)
        ua, ub = _dec(left.uncertainty), _dec(rv.uncertainty)
        value = a + b if op == "+" else a - b
        uncertainty = (ua * ua + ub * ub).sqrt()
        return Quantity(_to_float(value, "value"), left.unit,
                        _to_float(uncertainty, "uncertainty"))

    def _mul_div(self, op: str, left: Quantity, right: Quantity) -> Quantity:
        a, b = _dec(left.si_value), _dec(right.si_value)
        ua, ub = _dec(left.si_uncertainty), _dec(right.si_uncertainty)
        if op == "*":
            value = a * b
        else:
            if b == 0:
                raise EngineError(
                    ErrorCode.DIVISION_BY_ZERO,
                    "division by a zero-valued quantity",
                )
            value = a / b
        rel = (ua / a) ** 2 if a != 0 and ua != 0 else Decimal(0)
        rel += (ub / b) ** 2 if b != 0 and ub != 0 else Decimal(0)
        uncertainty = abs(value) * rel.sqrt()
        dimension = (left.unit.dimension * right.unit.dimension if op == "*"
                     else left.unit.dimension / right.unit.dimension)
        unit = self._display_unit(dimension)
        return Quantity(_to_float(value, "value"), unit,
                        _to_float(uncertainty, "uncertainty"))

    def _eval_power(self, node: Binary) -> Quantity:
        base = self._eval(node.left)
        exponent_q = self._eval(node.right)
        n_float = exponent_q.to_unit(self._one_unit(), self._registry).value
        n = int(n_float)
        if float(n) != n_float:
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"exponent must be an integer, got {n_float}",
            )
        a = _dec(base.si_value)
        ua = _dec(base.si_uncertainty)
        if a == 0 and n <= 0:
            raise EngineError(
                ErrorCode.DIVISION_BY_ZERO,
                "zero base raised to a non-positive power",
            )
        value = a ** n
        uncertainty = abs(Decimal(n) * a ** (n - 1)) * ua if ua else Decimal(0)
        dimension = base.unit.dimension ** n
        unit = self._display_unit(dimension)
        return Quantity(_to_float(value, "value"), unit,
                        _to_float(uncertainty, "uncertainty"))

    def _display_unit(self, dimension) -> Unit:
        found = self._registry.find_by_dimension(dimension)
        if found is not None:
            return found
        return Unit("(compound)", 1.0, dimension)

    def _one_unit(self) -> Unit:
        found = self._registry.find_by_dimension(DIMENSIONLESS)
        return found if found is not None else Unit("1", 1.0, DIMENSIONLESS)


# -- dimensionless unary functions: f(x) and its exact derivative ----------


def _abs_impl(x: Decimal) -> tuple[Decimal, Decimal]:
    return (abs(x), Decimal(1) if x >= 0 else Decimal(-1))


def _sqrt_impl(x: Decimal) -> tuple[Decimal, Decimal]:
    if x < 0:
        raise EngineError(ErrorCode.DOMAIN_ERROR, "sqrt of negative value")
    root = x.sqrt()
    if root == 0:
        raise EngineError(ErrorCode.DOMAIN_ERROR, "sqrt derivative undefined at 0")
    return root, Decimal("0.5") / root


def _sqr_impl(x: Decimal) -> tuple[Decimal, Decimal]:
    return x * x, 2 * x


def _exp_impl(x: Decimal) -> tuple[Decimal, Decimal]:
    value = x.exp()
    return value, value


def _ln_impl(x: Decimal) -> tuple[Decimal, Decimal]:
    if x <= 0:
        raise EngineError(ErrorCode.DOMAIN_ERROR, "ln of non-positive value")
    return x.ln(), 1 / x


def _log_impl(x: Decimal) -> tuple[Decimal, Decimal]:
    if x <= 0:
        raise EngineError(ErrorCode.DOMAIN_ERROR, "log of non-positive value")
    ln10 = Decimal(10).ln()
    return x.log10(), 1 / (x * ln10)


def _trig(fn: Callable[[Decimal], Decimal],
          deriv: Callable[[Decimal], Decimal], name: str):
    def impl(x: Decimal) -> tuple[Decimal, Decimal]:
        return fn(x), deriv(x)
    impl.__name__ = name
    return impl


def _pi() -> Decimal:
    """Hard-coded high-precision pi (50 digits), exceeding working precision."""
    return Decimal(
        "3.14159265358979323846264338327950288419716939937510"
    )


def _reduce_angle(x: Decimal) -> Decimal:
    """Reduce x modulo 2*pi into [-pi, pi] deterministically."""
    two_pi = 2 * _pi()
    # Use integer division of x by 2*pi at working precision.
    k = (x / two_pi).to_integral_value(rounding="ROUND_HALF_EVEN")
    r = x - k * two_pi
    if r > _pi():
        r -= two_pi
    elif r < -_pi():
        r += two_pi
    return r


def _series(x: Decimal, parity: str) -> Decimal:
    """Taylor series for sin (parity='odd') or cos (parity='even')."""
    x2 = x * x
    if parity == "odd":
        term = x
        total = x
        n = 1
    else:
        term = Decimal(1)
        total = Decimal(1)
        n = 0
    guard = Decimal(1).scaleb(-(DECIMAL_PRECISION - 4))
    while abs(term) > guard and n < 200:
        # Advance two degrees at a time: term_{n+2} = term_n * -x^2 /
        # ((2n+2)(2n+1)).
        denom = Decimal((2 * n + 2) * (2 * n + 1))
        term = -term * x2 / denom
        total += term
        n += 2
    return total


def _d_sin(x: Decimal) -> Decimal:
    return _series(_reduce_angle(x), "odd")


def _d_cos(x: Decimal) -> Decimal:
    return _series(_reduce_angle(x), "even")


def _d_tan(x: Decimal) -> Decimal:
    cosx = _d_cos(x)
    if cosx == 0:
        raise EngineError(ErrorCode.DOMAIN_ERROR, "tan is undefined at pi/2 + k*pi")
    return _d_sin(x) / cosx


_UNARY: dict[str, Callable[[Decimal], tuple[Decimal, Decimal]]] = {
    "abs": _abs_impl,
    "sqrt": _sqrt_impl,
    "sqr": _sqr_impl,
    "exp": _exp_impl,
    "ln": _ln_impl,
    "log": _log_impl,
    "sin": _trig(_d_sin, _d_cos, "sin"),
    "cos": _trig(_d_cos, lambda x: -_d_sin(x), "cos"),
    "tan": _trig(_d_tan, lambda x: 1 / (_d_cos(x) ** 2), "tan"),
}


def evaluate(expression: str, variables: dict[str, Quantity],
             registry: UnitRegistry | None = None) -> Quantity:
    return Evaluator(variables, registry).evaluate_expression(expression)
