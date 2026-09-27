"""Units, SI prefixes, named derived units and a unit registry.

A :class:`Unit` maps linearly to SI base units via a multiplicative
``factor``.  Compound units such as ``m/s^2`` or ``kN*m`` are parsed by
:meth:`UnitRegistry.resolve` into a single synthesized unit.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .dimensions import (
    AMOUNT,
    CURRENT,
    DIMENSIONLESS,
    LENGTH,
    LUMINOSITY,
    MASS,
    TEMPERATURE,
    TIME,
    Dimension,
)
from .errors import EngineError, ErrorCode

# SI decimal prefixes (longest first to make greedy matching deterministic).
PREFIXES: dict[str, float] = {
    "Q": 1e30, "R": 1e27, "Y": 1e24, "Z": 1e21,
    "E": 1e18, "P": 1e15, "T": 1e12, "G": 1e9, "M": 1e6, "k": 1e3,
    "h": 1e2, "da": 1e1,
    "d": 1e-1, "c": 1e-2, "m": 1e-3,
    "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12,
    "f": 1e-15, "a": 1e-18, "z": 1e-21, "y": 1e-24, "r": 1e-27, "q": 1e-30,
}

_TOKEN_RE = re.compile(r"\*|/|\^|[A-Za-zµΩ°]+|-?[0-9]+")


@dataclass(frozen=True)
class Unit:
    name: str
    factor: float
    dimension: Dimension
    coherent: bool = False

    def to_si(self, value: float) -> float:
        return value * self.factor

    def from_si(self, value: float) -> float:
        return value / self.factor


class UnitRegistry:
    def __init__(self) -> None:
        self._units: dict[str, Unit] = {}

    def register(self, unit: Unit) -> None:
        self._units[unit.name] = unit

    def get(self, name: str) -> Unit:
        try:
            return self._units[name]
        except KeyError:
            raise EngineError(
                ErrorCode.UNKNOWN_UNIT, f"unknown unit: {name!r}"
            ) from None

    # -- resolution ------------------------------------------------------

    def _resolve_atom(self, text: str) -> Unit:
        if text in self._units:
            return self._units[text]
        # Try SI prefix + registered unit, longest prefix first.
        for plen in sorted({len(p) for p in PREFIXES}, reverse=True):
            prefix, rest = text[:plen], text[plen:]
            if prefix in PREFIXES and rest in self._units:
                base = self._units[rest]
                return Unit(prefix + base.name,
                            base.factor * PREFIXES[prefix], base.dimension)
        raise EngineError(
            ErrorCode.UNKNOWN_UNIT, f"unknown unit: {text!r}"
        )

    def resolve(self, text: str) -> Unit:
        tokens = _TOKEN_RE.findall(text)
        if not tokens or "".join(tokens) != re.sub(r"\s+", "", text):
            raise EngineError(
                ErrorCode.UNKNOWN_UNIT, f"invalid unit expression: {text!r}"
            )

        def parse_term(pos: int) -> tuple[Unit, int]:
            if pos >= len(tokens) or tokens[pos] in ("*", "/", "^"):
                raise EngineError(
                    ErrorCode.UNKNOWN_UNIT,
                    f"invalid unit expression: {text!r}",
                )
            atom = self._resolve_atom(tokens[pos])
            pos += 1
            if pos < len(tokens) and tokens[pos] == "^":
                pos += 1
                if pos >= len(tokens) or not re.fullmatch(r"-?[0-9]+", tokens[pos]):
                    raise EngineError(
                        ErrorCode.UNKNOWN_UNIT,
                        f"invalid unit expression: {text!r}",
                    )
                power = int(tokens[pos])
                pos += 1
                atom = Unit(f"({atom.name})^{power}",
                            atom.factor ** power, atom.dimension ** power)
            return atom, pos

        first, pos = parse_term(0)
        result = first
        while pos < len(tokens):
            op = tokens[pos]
            if op not in ("*", "/"):
                raise EngineError(
                    ErrorCode.UNKNOWN_UNIT,
                    f"invalid unit expression: {text!r}",
                )
            pos += 1
            term, pos = parse_term(pos)
            if op == "*":
                result = Unit(f"({result.name}*{term.name})",
                              result.factor * term.factor,
                              result.dimension * term.dimension)
            else:
                result = Unit(f"({result.name}/{term.name})",
                              result.factor / term.factor,
                              result.dimension / term.dimension)
        return result

    def find_by_dimension(self, dimension: Dimension) -> Unit | None:
        """Return the preferred coherent display unit for a dimension.

        Only coherent SI units (base units and coherent derived units) are
        returned automatically.  Accepted non-SI units such as litres or
        minutes never shadow coherent composite dimensions such as m^3:
        when no coherent named unit exists, ``None`` is returned and the
        caller synthesizes a compound unit.
        """
        for unit in self._units.values():
            if unit.coherent and unit.dimension.matches(dimension):
                return unit
        return None


def _u(name: str, factor: float, dimension: Dimension,
       coherent: bool = False) -> Unit:
    return Unit(name, factor, dimension, coherent)


def default_registry() -> UnitRegistry:
    """SI base units, coherent derived units and accepted non-SI units."""
    reg = UnitRegistry()
    one = DIMENSIONLESS

    # SI base units.
    reg.register(_u("m", 1.0, LENGTH, True))
    reg.register(_u("kg", 1.0, MASS, True))
    reg.register(_u("g", 1e-3, MASS))
    reg.register(_u("s", 1.0, TIME, True))
    reg.register(_u("A", 1.0, CURRENT, True))
    reg.register(_u("K", 1.0, TEMPERATURE, True))
    reg.register(_u("mol", 1.0, AMOUNT, True))
    reg.register(_u("cd", 1.0, LUMINOSITY, True))
    reg.register(_u("one", 1.0, one, True))
    reg.register(_u("1", 1.0, one, True))
    reg.register(_u("rad", 1.0, one))
    reg.register(_u("sr", 1.0, one))

    # Coherent derived units.
    reg.register(_u("Hz", 1.0, one / TIME, True))
    reg.register(_u("N", 1.0, LENGTH * MASS / TIME ** 2, True))
    reg.register(_u("Pa", 1.0, MASS / (LENGTH * TIME ** 2), True))
    reg.register(_u("J", 1.0, LENGTH ** 2 * MASS / TIME ** 2, True))
    reg.register(_u("W", 1.0, LENGTH ** 2 * MASS / TIME ** 3, True))
    reg.register(_u("C", 1.0, CURRENT * TIME, True))
    reg.register(_u("V", 1.0, LENGTH ** 2 * MASS / (TIME ** 3 * CURRENT), True))
    reg.register(_u("ohm", 1.0,
                    LENGTH ** 2 * MASS / (TIME ** 3 * CURRENT ** 2), True))
    reg.register(_u("Ω", 1.0,
                    LENGTH ** 2 * MASS / (TIME ** 3 * CURRENT ** 2), True))
    reg.register(_u("S", 1.0,
                    TIME ** 3 * CURRENT ** 2 / (LENGTH ** 2 * MASS), True))
    reg.register(_u("F", 1.0,
                    TIME ** 4 * CURRENT ** 2 / (LENGTH ** 2 * MASS), True))
    reg.register(_u("T", 1.0, MASS / (TIME ** 2 * CURRENT), True))
    reg.register(_u("Wb", 1.0, LENGTH ** 2 * MASS / (TIME ** 2 * CURRENT), True))
    reg.register(_u("H", 1.0, LENGTH ** 2 * MASS / (TIME ** 2 * CURRENT ** 2), True))

    # Accepted non-SI units (exact conversions).
    reg.register(_u("min", 60.0, TIME))
    reg.register(_u("h", 3600.0, TIME))
    reg.register(_u("L", 1e-3, LENGTH ** 3))
    reg.register(_u("l", 1e-3, LENGTH ** 3))
    reg.register(_u("t", 1e3, MASS))
    reg.register(_u("bar", 1e5, MASS / (LENGTH * TIME ** 2)))
    reg.register(_u("eV", 1.602176634e-19,
                    LENGTH ** 2 * MASS / TIME ** 2))
    reg.register(_u("deg", math.pi / 180.0, one))
    reg.register(_u("°", math.pi / 180.0, one))
    reg.register(_u("percent", 1e-2, one))
    return reg
