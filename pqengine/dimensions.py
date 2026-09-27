"""Physical dimensions as exponent vectors over the 7 SI base dimensions.

Order: (length, mass, time, current, thermodynamic temperature,
amount of substance, luminous intensity).
"""

from __future__ import annotations

from dataclasses import dataclass

_BASE_NAMES = ("length", "mass", "time", "current", "temperature",
               "amount", "luminosity")
_RANK = len(_BASE_NAMES)


@dataclass(frozen=True)
class Dimension:
    """Integer exponent vector over the seven SI base dimensions."""

    exponents: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.exponents) != _RANK:
            raise ValueError(f"dimension vector must have length {_RANK}")

    def is_dimensionless(self) -> bool:
        return all(e == 0 for e in self.exponents)

    def matches(self, other: Dimension) -> bool:
        return self.exponents == other.exponents

    def __mul__(self, other: Dimension) -> Dimension:
        return Dimension(tuple(a + b for a, b in zip(self.exponents, other.exponents)))

    def __truediv__(self, other: Dimension) -> Dimension:
        return Dimension(tuple(a - b for a, b in zip(self.exponents, other.exponents)))

    def __pow__(self, power: int) -> Dimension:
        if not isinstance(power, int):
            raise TypeError("dimension power must be an integer")
        return Dimension(tuple(e * power for e in self.exponents))

    def __str__(self) -> str:
        if self.is_dimensionless():
            return "1"
        parts: list[str] = []
        for name, exp in zip(_BASE_NAMES, self.exponents):
            if exp == 0:
                continue
            parts.append(name if exp == 1 else f"{name}^{exp}")
        return "·".join(parts)


def _base(index: int) -> Dimension:
    vec = [0] * _RANK
    vec[index] = 1
    return Dimension(tuple(vec))


DIMENSIONLESS = Dimension(tuple(0 for _ in range(_RANK)))
LENGTH = _base(0)
MASS = _base(1)
TIME = _base(2)
CURRENT = _base(3)
TEMPERATURE = _base(4)
AMOUNT = _base(5)
LUMINOSITY = _base(6)
