"""Physical quantity: finite value, standard uncertainty and a unit."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .errors import EngineError, ErrorCode
from .units import Unit, UnitRegistry, default_registry


def _require_finite(name: str, number: float) -> None:
    if not math.isfinite(number):
        raise EngineError(
            ErrorCode.NON_FINITE_VALUE,
            f"{name} must be finite, got {number!r}",
        )


@dataclass(frozen=True)
class Quantity:
    value: float
    unit: Unit
    uncertainty: float = 0.0

    def __post_init__(self) -> None:
        _require_finite("value", self.value)
        _require_finite("uncertainty", self.uncertainty)
        if self.uncertainty < 0.0:
            raise EngineError(
                ErrorCode.UNCERTAINTY_INVALID,
                f"uncertainty must be non-negative, got {self.uncertainty!r}",
            )

    @property
    def si_value(self) -> float:
        return self.unit.to_si(self.value)

    @property
    def si_uncertainty(self) -> float:
        return self.unit.to_si(self.uncertainty)

    def to_unit(self, target: Unit | str,
                registry: UnitRegistry | None = None) -> Quantity:
        """Convert to ``target``; dimensions must match exactly.

        The conversion is atomic from the caller's perspective: a mismatch
        raises before any value is produced.
        """
        if isinstance(target, str):
            reg = registry if registry is not None else default_registry()
            target = reg.resolve(target)
        if not self.unit.dimension.matches(target.dimension):
            raise EngineError(
                ErrorCode.UNIT_CONVERSION_FAILED,
                f"cannot convert {self.unit.name!r} ({self.unit.dimension}) "
                f"to {target.name!r} ({target.dimension})",
            )
        si = self.unit.to_si(self.value)
        return Quantity(
            target.from_si(si),
            target,
            abs(self.uncertainty * self.unit.factor / target.factor),
        )


def make_quantity(value: float, unit_text: str, uncertainty: float = 0.0,
                  registry: UnitRegistry | None = None) -> Quantity:
    reg = registry if registry is not None else default_registry()
    unit = reg.resolve(unit_text)
    return Quantity(value, unit, uncertainty)
