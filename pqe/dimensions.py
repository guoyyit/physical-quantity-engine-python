"""Physical dimensions as integer exponent vectors over the 7 SI base dimensions.

Vector order: (length, mass, time, electric_current, temperature, amount,
luminous_intensity).
"""
from __future__ import annotations

from dataclasses import dataclass

# Order of the seven SI base dimensions.
NAMES = ("L", "M", "T", "I", "Θ", "N", "J")

_SCALAR = (0, 0, 0, 0, 0, 0, 0)
_LENGTH = (1, 0, 0, 0, 0, 0, 0)
_MASS = (0, 1, 0, 0, 0, 0, 0)
_TIME = (0, 0, 1, 0, 0, 0, 0)
_CURRENT = (0, 0, 0, 1, 0, 0, 0)
_TEMPERATURE = (0, 0, 0, 0, 1, 0, 0)
_AMOUNT = (0, 0, 0, 0, 0, 1, 0)
_LUMINOUS_INTENSITY = (0, 0, 0, 0, 0, 0, 1)


@dataclass(frozen=True)
class Dimension:
    """An immutable exponent vector, e.g. velocity = L*T^-1."""

    exponents: tuple[int, ...]

    def __post_init__(self) -> None:
        exps = self.exponents
        if not isinstance(exps, tuple) or len(exps) != 7:
            raise ValueError("dimension must be a tuple of 7 integer exponents")
        for e in exps:
            if isinstance(e, bool) or not isinstance(e, int):
                raise ValueError("dimension exponents must be integers")
        # Normalize so equal dimensions are identical objects of content.
        object.__setattr__(self, "exponents", tuple(exps))

    @classmethod
    def scalar(cls) -> "Dimension":
        return cls(_SCALAR)

    @classmethod
    def length(cls) -> "Dimension":
        return cls(_LENGTH)

    @classmethod
    def mass(cls) -> "Dimension":
        return cls(_MASS)

    @classmethod
    def time(cls) -> "Dimension":
        return cls(_TIME)

    @classmethod
    def current(cls) -> "Dimension":
        return cls(_CURRENT)

    @classmethod
    def temperature(cls) -> "Dimension":
        return cls(_TEMPERATURE)

    @classmethod
    def amount(cls) -> "Dimension":
        return cls(_AMOUNT)

    @classmethod
    def luminous_intensity(cls) -> "Dimension":
        return cls(_LUMINOUS_INTENSITY)

    def is_dimensionless(self) -> bool:
        return self.exponents == _SCALAR

    def __mul__(self, other: "Dimension") -> "Dimension":
        return Dimension(tuple(a + b for a, b in zip(self.exponents, other.exponents)))

    def __truediv__(self, other: "Dimension") -> "Dimension":
        return Dimension(tuple(a - b for a, b in zip(self.exponents, other.exponents)))

    def __pow__(self, n: int) -> "Dimension":
        if isinstance(n, bool) or not isinstance(n, int):
            raise TypeError("dimension exponent must be an integer")
        return Dimension(tuple(e * n for e in self.exponents))

    def compatible_with(self, other: "Dimension") -> bool:
        return self.exponents == other.exponents

    def format(self) -> str:
        """Deterministic human-readable form, e.g. ``L*T^-1``; ``1`` if scalar."""
        parts: list[str] = []
        for name, exp in zip(NAMES, self.exponents):
            if exp == 0:
                continue
            parts.append(name if exp == 1 else f"{name}^{exp}")
        return "*".join(parts) if parts else "1"

    def __str__(self) -> str:
        return self.format()


DIMENSIONLESS = Dimension.scalar()
LENGTH = Dimension.length()
MASS = Dimension.mass()
TIME = Dimension.time()
CURRENT = Dimension.current()
TEMPERATURE = Dimension.temperature()
AMOUNT = Dimension.amount()
LUMINOUS_INTENSITY = Dimension.luminous_intensity()
