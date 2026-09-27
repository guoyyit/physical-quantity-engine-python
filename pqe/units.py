"""Units: SI base units, prefixes and named derived units; parsing and scaling.

Supported names (see docs/units.md):

* base: m, g, s, A, K, mol, cd
* prefixed: all SI prefixes (u and micro both accepted), e.g. km, mm, MHz, kN
* derived named units: Hz, N, Pa, J, W, C, V, F, Ohm, S, Wb, T, H, Gy, Sv
* non-SI accepted: min, h, d(day), L, t, eV, degC (offset unit, standalone only)

Compound units use ``*`` (or whitespace), ``/`` and ``^n`` with positive integer
exponents, for example ``m/s^2``, ``kg*m^-2``, ``N*m``.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .dimensions import (
    AMOUNT,
    CURRENT,
    DIMENSIONLESS,
    Dimension,
    LENGTH,
    LUMINOUS_INTENSITY,
    MASS,
    TEMPERATURE,
    TIME,
)
from .errors import ErrorCode, EngineError
from .numeric import ONE, ZERO, to_decimal

# Prefix name -> multiplier. Greek mu and ASCII u are both accepted.
PREFIXES: dict[str, Decimal] = {
    "Q": Decimal("1e30"),
    "R": Decimal("1e27"),
    "Y": Decimal("1e24"),
    "Z": Decimal("1e21"),
    "E": Decimal("1e18"),
    "P": Decimal("1e15"),
    "T": Decimal("1e12"),
    "G": Decimal("1e9"),
    "M": Decimal("1e6"),
    "k": Decimal("1e3"),
    "h": Decimal("1e2"),
    "da": Decimal("1e1"),
    "d": Decimal("1e-1"),
    "c": Decimal("1e-2"),
    "m": Decimal("1e-3"),
    "u": Decimal("1e-6"),
    "µ": Decimal("1e-6"),
    "n": Decimal("1e-9"),
    "p": Decimal("1e-12"),
    "f": Decimal("1e-15"),
    "a": Decimal("1e-18"),
    "z": Decimal("1e-21"),
    "y": Decimal("1e-24"),
    "r": Decimal("1e-27"),
    "q": Decimal("1e-30"),
}

_DIM_SCALAR = DIMENSIONLESS
_DIM_VELOCITY = LENGTH / TIME
_DIM_ACCEL = _DIM_VELOCITY / TIME
_DIM_FORCE = MASS * _DIM_ACCEL
_DIM_ENERGY = _DIM_FORCE * LENGTH
_DIM_POWER = _DIM_ENERGY / TIME
_DIM_CHARGE = CURRENT * TIME
_DIM_VOLTAGE = _DIM_ENERGY / _DIM_CHARGE
_DIM_RESISTANCE = _DIM_VOLTAGE / CURRENT
_DIM_AREA = LENGTH ** 2
_DIM_VOLUME = LENGTH ** 3
_DIM_FREQUENCY = TIME ** -1
_DIM_PRESSURE = _DIM_FORCE / _DIM_AREA
_DIM_CAPACITANCE = _DIM_CHARGE / _DIM_VOLTAGE
_DIM_CONDUCTANCE = CURRENT / _DIM_VOLTAGE
_DIM_MAG_FLUX = _DIM_VOLTAGE * TIME
_DIM_MAG_FIELD = _DIM_MAG_FLUX / _DIM_AREA
_DIM_INDUCTANCE = _DIM_MAG_FLUX / CURRENT


@dataclass(frozen=True)
class Unit:
    """A unit convertible to SI base units via ``value_base = scale*value + offset``.

    scale/offset are expressed relative to coherent SI base units (kg for mass).
    """

    name: str
    dimension: Dimension
    scale: Decimal
    offset: Decimal = ZERO
    prefixable: bool = False

    def to_base(self, value: Decimal) -> Decimal:
        return value * self.scale + self.offset

    def from_base(self, value: Decimal) -> Decimal:
        return (value - self.offset) / self.scale


# name -> (dimension, scale, offset, prefixable)
_BASE_UNITS: dict[str, tuple[Dimension, Decimal, Decimal, bool]] = {
    "m": (LENGTH, ONE, ZERO, True),
    # Gram is registered as a base name; kg is the prefixed coherent unit.
    "g": (MASS, Decimal("0.001"), ZERO, True),
    "s": (TIME, ONE, ZERO, True),
    "A": (CURRENT, ONE, ZERO, True),
    "K": (TEMPERATURE, ONE, ZERO, True),
    "mol": (AMOUNT, ONE, ZERO, True),
    "cd": (LUMINOUS_INTENSITY, ONE, ZERO, True),
}

# name -> (dimension, scale relative to SI base units, prefixable)
_DERIVED_UNITS: dict[str, tuple[Dimension, Decimal, bool]] = {
    "Hz": (_DIM_FREQUENCY, ONE, True),
    "N": (_DIM_FORCE, ONE, True),
    "Pa": (_DIM_PRESSURE, ONE, True),
    "J": (_DIM_ENERGY, ONE, True),
    "W": (_DIM_POWER, ONE, True),
    "C": (_DIM_CHARGE, ONE, True),
    "V": (_DIM_VOLTAGE, ONE, True),
    "F": (_DIM_CAPACITANCE, ONE, True),
    "Ohm": (_DIM_RESISTANCE, ONE, True),
    "Ω": (_DIM_RESISTANCE, ONE, False),
    "S": (_DIM_CONDUCTANCE, ONE, True),
    "Wb": (_DIM_MAG_FLUX, ONE, True),
    "T": (_DIM_MAG_FIELD, ONE, True),
    "H": (_DIM_INDUCTANCE, ONE, True),
    "rad": (_DIM_SCALAR, ONE, False),
    "sr": (_DIM_SCALAR, ONE, False),
    "Gy": (_DIM_ENERGY / MASS, ONE, False),
    "Sv": (_DIM_ENERGY / MASS, ONE, False),
}

# Accepted non-SI units (name -> dimension, scale, offset, prefixable).
_OTHER_UNITS: dict[str, tuple[Dimension, Decimal, Decimal, bool]] = {
    "min": (TIME, Decimal("60"), ZERO, False),
    "h": (TIME, Decimal("3600"), ZERO, False),
    "d": (TIME, Decimal("86400"), ZERO, False),
    "L": (_DIM_VOLUME, Decimal("0.001"), ZERO, True),
    "l": (_DIM_VOLUME, Decimal("0.001"), ZERO, False),
    "t": (MASS, Decimal("1000"), ZERO, False),
    "eV": (_DIM_ENERGY, Decimal("1.602176634e-19"), ZERO, True),
    "degC": (TEMPERATURE, ONE, Decimal("273.15"), False),
    "°C": (TEMPERATURE, ONE, Decimal("273.15"), False),
    "percent": (_DIM_SCALAR, Decimal("0.01"), ZERO, False),
}


class _UnitToken:
    """One atom of a compound unit expression: name plus optional exponent."""

    def __init__(self, text: str, pos: int) -> None:
        self.text = text
        self.pos = pos


class UnitSystem:
    """Registry of base, prefixed and named units with a compound parser."""

    def __init__(self) -> None:
        self._units: dict[str, Unit] = {}
        self._register_all()

    # -- registration -----------------------------------------------------
    def _add(self, name: str, dim: Dimension, scale: Decimal,
             offset: Decimal = ZERO, prefixable: bool = False) -> None:
        self._units[name] = Unit(name, dim, scale, offset, prefixable)

    def _register_all(self) -> None:
        # 1) Bare base units.
        for name, (dim, scale, _, prefixable) in _BASE_UNITS.items():
            self._add(name, dim, scale, ZERO, prefixable)
        # 2) Bare named derived units.
        for name, (dim, scale, prefixable) in _DERIVED_UNITS.items():
            self._add(name, dim, scale, ZERO, prefixable)
        # 3) Bare accepted non-SI units.
        for name, (dim, scale, offset, prefixable) in _OTHER_UNITS.items():
            self._add(name, dim, scale, offset, prefixable)
        # 4) Prefixed forms, generated from bare names only.
        bare = dict(self._units)
        for bare_name, unit in bare.items():
            if not unit.prefixable:
                continue
            for pfx, mult in PREFIXES.items():
                candidate = pfx + bare_name
                if candidate in self._units:
                    continue
                self._add(candidate, unit.dimension, mult * unit.scale)

    # -- lookup -----------------------------------------------------------
    def lookup(self, name: str) -> Unit:
        unit = self._units.get(name)
        if unit is not None:
            return unit
        raise EngineError(
            ErrorCode.UNKNOWN_UNIT, f"unknown unit: {name!r}"
        )

    def known_units(self) -> list[str]:
        return sorted(self._units)

    # -- parsing ----------------------------------------------------------
    def parse(self, text: str | None) -> Unit:
        """Parse a simple or compound unit into one convertible :class:`Unit`."""
        if text is None:
            return Unit("", _DIM_SCALAR, ONE)
        text = text.strip()
        if not text:
            raise EngineError(
                ErrorCode.UNKNOWN_UNIT, "invalid unit: empty unit expression"
            )
        # A bare registered name (including offset units such as degC) is
        # returned directly; offset units cannot appear in compounds.
        bare = self._units.get(text)
        if bare is not None:
            return bare
        if not any(ch in text for ch in "*/^ \t"):
            # Looks like a single name but is unknown.
            raise EngineError(
                ErrorCode.UNKNOWN_UNIT, f"unknown unit: {text!r}")
        return _CompoundParser(self, text).parse()


class _CompoundParser:
    """Parse compound units such as ``kg*m/s^2`` into a single Unit."""

    def __init__(self, system: UnitSystem, text: str) -> None:
        self.system = system
        self.text = text
        self.pos = 0
        self.n = len(text)

    def parse(self) -> Unit:
        dim = _DIM_SCALAR
        scale = ONE
        num_parts: list[str] = []
        den_parts: list[str] = []
        expect_factor = True
        # +1 while in the numerator, -1 while in the denominator.
        position_sign = 1
        while True:
            self._skip_ws()
            if self.pos >= self.n:
                break
            if expect_factor:
                if self.text[self.pos] in ("*", "/"):
                    raise self._error(
                        f"unexpected operator {self.text[self.pos]!r}")
            else:
                ch = self.text[self.pos]
                if ch not in ("*", "/"):
                    raise self._error(f"expected '*' or '/' near {ch!r}")
                position_sign = -1 if ch == "/" else 1
                self.pos += 1
                self._skip_ws()
                if self.pos >= self.n:
                    raise self._error(
                        f"missing unit after operator {ch!r}")
            atom_name, power = self._read_factor()
            exponent = position_sign * power
            unit = self.system.lookup(atom_name)
            if unit.offset != ZERO:
                raise EngineError(
                    ErrorCode.UNIT_CONVERSION_FAILED,
                    f"offset unit {atom_name!r} cannot be used in a compound unit",
                )
            dim = dim * (unit.dimension ** exponent)
            scale = scale * (unit.scale ** exponent)
            rendered = atom_name if power == 1 else f"{atom_name}^{power}"
            if position_sign == 1:
                num_parts.append(rendered)
            else:
                den_parts.append(rendered)
            expect_factor = False
        if expect_factor:
            raise self._error("empty unit expression")
        name = "*".join(num_parts)
        if den_parts:
            name += "/" + "*".join(den_parts)
        return Unit(name, dim, scale, ZERO)

    def _read_factor(self) -> tuple[str, int]:
        start = self.pos
        # A unit name is a run of letters (incl. Greek °) or percent sign.
        while self.pos < self.n and (self.text[self.pos].isalpha()
                                     or self.text[self.pos] in "°%"):
            self.pos += 1
        if self.pos == start:
            raise self._error("expected a unit name")
        name = self.text[start:self.pos]
        exponent = 1
        self._skip_ws()
        if self.pos < self.n and self.text[self.pos] == "^":
            self.pos += 1
            self._skip_ws()
            exponent = self._read_int()
        return name, exponent

    def _read_int(self) -> int:
        start = self.pos
        if self.pos < self.n and self.text[self.pos] in "+-":
            self.pos += 1
        digits_start = self.pos
        while self.pos < self.n and self.text[self.pos].isdigit():
            self.pos += 1
        if self.pos == digits_start:
            raise self._error("expected integer exponent after '^'")
        return int(self.text[start:self.pos])

    def _skip_ws(self) -> None:
        while self.pos < self.n and self.text[self.pos] in " \t":
            self.pos += 1

    def _error(self, detail: str) -> EngineError:
        return EngineError(
            ErrorCode.UNKNOWN_UNIT,
            f"invalid unit {self.text!r}: {detail}",
        )
