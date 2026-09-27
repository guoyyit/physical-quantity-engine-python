"""Expression evaluation: dimension checks, arithmetic and unit conversion.

Evaluation runs against one immutable :class:`~pqe.catalog.CatalogVersion`.
Named quantities become their stored SI-base physical quantities; numeric
literals and built-in constants (``pi``, ``e``) are dimensionless.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from .catalog import Catalog, CatalogVersion
from .errors import ErrorCode, EngineError
from .numeric import (
    CONTEXT_PRECISION,
    engine_context,
    format_decimal,
    round_result,
    round_uncertainty,
    to_decimal,
)
from .parser import (
    Binary,
    FuncCall,
    Name,
    Node,
    Number,
    Unary,
    parse,
)
from .quantity import PhysicalQuantity, constants
from .units import Unit, UnitSystem

CancellationCheck = Callable[[], None]

# SI coherent base unit per base dimension index.
_BASE_UNIT_NAMES = ("m", "kg", "s", "A", "K", "mol", "cd")


def _present(value: Decimal,
             uncertainty: Decimal | None) -> tuple[Decimal, Decimal | None]:
    """Round (value, uncertainty) with the fixed presentation rule.

    If rounding collapses the uncertainty to zero, the value is presented
    with the default 12-significant-digit rule rather than a false
    over-precise alignment to zero.
    """
    if uncertainty is None:
        return round_result(value, None), None
    rounded_unc = round_uncertainty(uncertainty)
    # If the uncertainty rounds to zero, or its decimal place is finer
    # than the working precision can align to next to the value, present
    # the value at the standard rule and report no meaningful uncertainty.
    place_gap = abs(value.adjusted() - rounded_unc.adjusted())
    if rounded_unc == 0 or place_gap >= CONTEXT_PRECISION:
        return round_result(value, None), None
    return round_result(value, uncertainty), rounded_unc


@dataclass(frozen=True)
class EvalResult:
    value: Decimal                 # in SI base units (unrounded internal value)
    value_text: str                # rounded value expressed in output unit
    unit: str                      # output unit name
    uncertainty: Decimal | None    # rounded uncertainty in output unit, or None
    uncertainty_text: str | None
    dimension: tuple[int, ...]
    version: int
    expression: str

    def to_dict(self) -> dict:
        return {
            "value": self.value_text,
            "unit": self.unit,
            "uncertainty": self.uncertainty_text,
            "dimension": self.dimension,
            "version": self.version,
            "expression": self.expression,
        }


class Evaluator:
    def __init__(self, catalog: Catalog, units: UnitSystem) -> None:
        self.catalog = catalog
        self.units = units
        self._constants = constants()

    # -- public API -------------------------------------------------------
    def evaluate(self, expression: str, version: int | None = None,
                 output_unit: str | None = None,
                 cancel: CancellationCheck | None = None) -> EvalResult:
        cancel = cancel or (lambda: None)
        tree = parse(expression)
        target = self.catalog.get_version(
            version if version is not None else self.catalog.head_version())
        env = self._build_env(target)
        q = self.eval_node(tree, env, target.version, expression, cancel)
        unit = self._resolve_output_unit(q, output_unit, expression)
        return self._build_result(q, unit, target.version, expression)

    def convert(self, value: str, unit: str, target_unit: str,
                uncertainty: str | None = None) -> dict:
        """Convert a single value between compatible units.

        Validation and conversion are fully ordered; on any failure nothing
        is returned (an EngineError with a stable code is raised instead).
        """
        src = self.units.parse(unit)
        dst = self.units.parse(target_unit)
        if not src.dimension.compatible_with(dst.dimension):
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"cannot convert {src.dimension.format()} ({src.name}) to "
                f"{dst.dimension.format()} ({dst.name})")
        raw = to_decimal(value)
        raw_unc = to_decimal(uncertainty) if uncertainty is not None else None
        if raw_unc is not None and raw_unc < 0:
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT,
                "uncertainty must be non-negative")
        with engine_context():
            base = src.to_base(raw)
            if not base.is_finite():
                raise EngineError(
                    ErrorCode.NON_FINITE_VALUE,
                    "conversion produced a non-finite value")
            out = dst.from_base(base)
            out_unc = None
            if raw_unc is not None:
                base_unc = raw_unc * src.scale
                out_unc = base_unc / dst.scale
        rounded_value, rounded_unc = _present(out, out_unc)
        return {
            "value": format_decimal(rounded_value),
            "unit": dst.name,
            "uncertainty": (format_decimal(rounded_unc)
                            if rounded_unc is not None else None),
            "dimension": dst.dimension.exponents,
        }

    # -- internals --------------------------------------------------------
    def _build_env(self, version: CatalogVersion) -> dict[str, PhysicalQuantity]:
        env: dict[str, PhysicalQuantity] = {}
        for name, entry in version.entries.items():
            env[name] = entry.to_quantity()
        # Constants may not be shadowed by catalog names.
        for name, q in self._constants.items():
            if name in env:
                raise EngineError(
                    ErrorCode.CATALOG_CONFLICT,
                    f"catalog quantity {name!r} shadows a reserved constant")
            env[name] = q
        return env

    def _resolve_output_unit(self, q: PhysicalQuantity, requested: str | None,
                             expression: str) -> Unit:
        if requested is None:
            return self._default_unit(q)
        unit = self.units.parse(requested)
        if not unit.dimension.compatible_with(q.dimension):
            raise EngineError(
                ErrorCode.DIMENSION_MISMATCH,
                f"result of {expression!r} has dimension "
                f"{q.dimension.format()} but output unit {requested!r} has "
                f"dimension {unit.dimension.format()}")
        return unit

    def _default_unit(self, q: PhysicalQuantity) -> Unit:
        exps = q.dimension.exponents
        parts: list[str] = []
        scale = Decimal(1)
        for exp, base_name in zip(exps, _BASE_UNIT_NAMES):
            if exp == 0:
                continue
            base_unit = self.units.lookup(base_name)
            parts.append(base_name if exp == 1 else f"{base_name}^{exp}")
        if not parts:
            return Unit("", q.dimension, Decimal(1))
        name = "*".join(parts)
        return Unit(name, q.dimension, scale)

    def _build_result(self, q: PhysicalQuantity, unit: Unit,
                      version: int, expression: str) -> EvalResult:
        with engine_context():
            out_value = unit.from_base(q.value)
            out_unc = (q.uncertainty / unit.scale
                       if q.uncertainty is not None else None)
            if not out_value.is_finite():
                raise EngineError(
                    ErrorCode.NON_FINITE_VALUE,
                    "result converted to a non-finite value")
            rounded_value, rounded_unc = _present(out_value, out_unc)
        return EvalResult(
            value=q.value,
            value_text=format_decimal(rounded_value),
            unit=unit.name,
            uncertainty=rounded_unc,
            uncertainty_text=(format_decimal(rounded_unc)
                              if rounded_unc is not None else None),
            dimension=q.dimension.exponents,
            version=version,
            expression=expression,
        )

    def eval_node(self, node: Node, env: dict[str, PhysicalQuantity],
                  version: int, expression: str,
                  cancel: CancellationCheck) -> PhysicalQuantity:
        cancel()
        if isinstance(node, Number):
            return PhysicalQuantity(to_decimal(node.text),
                                    self._scalar_dimension())
        if isinstance(node, Name):
            q = env.get(node.name)
            if q is None:
                raise EngineError(
                    ErrorCode.UNKNOWN_NAME,
                    f"unknown name {node.name!r} in {expression!r}")
            return q
        if isinstance(node, Unary):
            operand = self.eval_node(node.operand, env, version,
                                     expression, cancel)
            if node.op == "-":
                return operand.neg()
            return operand.pos()
        if isinstance(node, FuncCall):
            arg = self.eval_node(node.arg, env, version, expression, cancel)
            return arg.apply_unary(node.name)
        if isinstance(node, Binary):
            return self._eval_binary(node, env, version, expression, cancel)
        raise EngineError(
            ErrorCode.INTERNAL_ERROR, f"unsupported AST node {type(node)!r}")

    def _eval_binary(self, node: Binary, env, version, expression,
                     cancel) -> PhysicalQuantity:
        if node.op == "^":
            base = self.eval_node(node.left, env, version, expression, cancel)
            exponent_node = node.right
            # The parser guarantees ^ RHS is an integer Number.
            if not isinstance(exponent_node, Number):
                raise EngineError(
                    ErrorCode.PARSE_ERROR,
                    "exponent must be an integer literal")
            n = int(exponent_node.text)
            return base.power_int(n)
        left = self.eval_node(node.left, env, version, expression, cancel)
        right = self.eval_node(node.right, env, version, expression, cancel)
        if node.op == "+":
            return left.add(right)
        if node.op == "-":
            return left.sub(right)
        if node.op == "*":
            return left.mul(right)
        if node.op == "/":
            return left.truediv(right)
        raise EngineError(
            ErrorCode.INTERNAL_ERROR, f"unknown operator {node.op!r}")

    @staticmethod
    def _scalar_dimension():
        from .dimensions import Dimension
        return Dimension.scalar()
