"""Append-only, versioned, atomic catalog of named physical quantities.

Every successful commit installs a brand-new immutable :class:`CatalogVersion`
atomically (under a lock). Evaluations always run against a single complete
version, so a concurrent commit can never produce a mixed view.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from .dimensions import Dimension
from .errors import ErrorCode, EngineError
from .numeric import to_decimal
from .quantity import PhysicalQuantity
from .units import UnitSystem


@dataclass(frozen=True)
class CatalogEntry:
    name: str
    value: Decimal                       # in SI base units
    dimension: Dimension
    unit: str                            # display unit as supplied
    uncertainty: Decimal | None = None   # in SI base units

    def to_quantity(self) -> PhysicalQuantity:
        return PhysicalQuantity(self.value, self.dimension, self.uncertainty)


@dataclass(frozen=True)
class CatalogVersion:
    version: int
    entries: MappingProxyType

    def get(self, name: str) -> CatalogEntry:
        entry = self.entries.get(name)
        if entry is None:
            raise EngineError(
                ErrorCode.UNKNOWN_NAME,
                f"physical quantity {name!r} is not defined in version "
                f"{self.version}")
        return entry


class Catalog:
    """Thread-safe catalog; each commit creates a new immutable version."""

    def __init__(self, units: UnitSystem) -> None:
        self._units = units
        self._lock = threading.RLock()
        # version 0 is an immutable empty catalog.
        empty: dict[str, CatalogEntry] = {}
        self._versions: list[CatalogVersion] = [
            CatalogVersion(0, MappingProxyType(empty))]

    # -- reads ------------------------------------------------------------
    def head_version(self) -> int:
        return self._versions[-1].version

    def get_version(self, version: int) -> CatalogVersion:
        if not isinstance(version, int) or isinstance(version, bool):
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT, "version must be an integer")
        with self._lock:
            if version < 0 or version >= len(self._versions):
                raise EngineError(
                    ErrorCode.VERSION_NOT_FOUND,
                    f"catalog version {version} does not exist; "
                    f"head is {self.head_version()}")
            return self._versions[version]

    def snapshot(self) -> CatalogVersion:
        return self._versions[-1]

    # -- writes -----------------------------------------------------------
    def make_entry(self, name: str, value: str, unit: str,
                   uncertainty: str | None = None) -> CatalogEntry:
        if not isinstance(name, str) or not name:
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT, "quantity name must be non-empty")
        if not name[0].isalpha() and name[0] != "_" or not all(
                c.isalnum() or c == "_" for c in name):
            raise EngineError(
                ErrorCode.INVALID_ARGUMENT,
                f"invalid quantity name {name!r}")
        parsed_unit = self._units.parse(unit)
        raw_value = to_decimal(value)
        with self._units_engine_context():
            base_value = parsed_unit.to_base(raw_value)
        if not base_value.is_finite():
            raise EngineError(
                ErrorCode.NON_FINITE_VALUE,
                f"value for {name!r} converts to a non-finite result")
        base_uncertainty: Decimal | None = None
        if uncertainty is not None:
            raw_unc = to_decimal(uncertainty)
            if raw_unc < 0:
                raise EngineError(
                    ErrorCode.INVALID_ARGUMENT,
                    f"uncertainty for {name!r} must be non-negative")
            with self._units_engine_context():
                base_uncertainty = raw_unc * parsed_unit.scale
            if not base_uncertainty.is_finite():
                raise EngineError(
                    ErrorCode.NON_FINITE_VALUE,
                    f"uncertainty for {name!r} converts to a non-finite result")
        return CatalogEntry(
            name=name,
            value=base_value,
            dimension=parsed_unit.dimension,
            unit=parsed_unit.name,
            uncertainty=base_uncertainty,
        )

    def commit(self, entries: dict[str, CatalogEntry],
               base_version: int | None = None) -> CatalogVersion:
        """Atomically add/update *entries* on top of *base_version*.

        The new version is built entirely before it is published; readers
        therefore never observe a partially built version. When
        *base_version* is given it must equal the current head, otherwise
        :class:`EngineError` with CATALOG_CONFLICT is raised (optimistic
        concurrency control).
        """
        with self._lock:
            current_head = self.head_version()
            if base_version is not None and base_version != current_head:
                raise EngineError(
                    ErrorCode.CATALOG_CONFLICT,
                    f"commit based on version {base_version} but head is "
                    f"{current_head}")
            base = self.get_version(current_head)
            merged: dict[str, CatalogEntry] = dict(base.entries)
            for key, entry in entries.items():
                if entry.name != key:
                    raise EngineError(
                        ErrorCode.INVALID_ARGUMENT,
                        f"entry key {key!r} does not match name {entry.name!r}")
                merged[key] = entry
            new_version = CatalogVersion(
                current_head + 1, MappingProxyType(merged))
            self._versions.append(new_version)
            return new_version

    def add(self, name: str, value: str, unit: str,
            uncertainty: str | None = None,
            base_version: int | None = None) -> CatalogVersion:
        """Validate, convert and publish a single entry atomically."""
        entry = self.make_entry(name, value, unit, uncertainty)
        return self.commit({name: entry}, base_version)

    @staticmethod
    def _units_engine_context():
        from .numeric import engine_context
        return engine_context()
