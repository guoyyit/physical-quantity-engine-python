"""Atomic, versioned catalog of named physical quantities.

Each :meth:`Catalog.commit` publishes a brand-new immutable
:class:`CatalogVersion`.  Readers always evaluate against a complete
snapshot and can never observe a mixed state while a concurrent commit is
in progress.  Optimistic concurrency control rejects a commit whose
``expected_version`` no longer matches the current version.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .errors import EngineError, ErrorCode
from .quantity import Quantity


@dataclass(frozen=True)
class CatalogVersion:
    version: int
    entries: dict[str, Quantity]


class Catalog:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        empty = CatalogVersion(0, {})
        self._history: list[CatalogVersion] = [empty]

    def current(self) -> CatalogVersion:
        with self._lock:
            return self._history[-1]

    def get_version(self, version: int) -> CatalogVersion:
        with self._lock:
            if version < 0 or version >= len(self._history):
                raise EngineError(
                    ErrorCode.VERSION_NOT_FOUND,
                    f"catalog version {version} does not exist "
                    f"(current: {self._history[-1].version})",
                )
            return self._history[version]

    def list_versions(self) -> list[int]:
        with self._lock:
            return [v.version for v in self._history]

    def commit(self, entries: dict[str, Quantity],
               expected_version: int | None = None) -> CatalogVersion:
        """Atomically publish ``entries`` as a brand-new complete version.

        ``entries`` is the *full* contents of the new version (not a diff).
        When ``expected_version`` is given it must equal the current
        version, otherwise :class:`EngineError` with
        ``CATALOG_CONFLICT`` is raised and nothing is published.
        """
        with self._lock:
            latest = self._history[-1]
            if expected_version is not None and expected_version != latest.version:
                raise EngineError(
                    ErrorCode.CATALOG_CONFLICT,
                    f"expected version {expected_version}, "
                    f"current is {latest.version}",
                )
            snapshot = CatalogVersion(latest.version + 1, dict(entries))
            self._history.append(snapshot)
            return snapshot

    def lookup(self, version: int, name: str) -> Quantity:
        v = self.get_version(version)
        try:
            return v.entries[name]
        except KeyError:
            raise EngineError(
                ErrorCode.UNKNOWN_QUANTITY,
                f"quantity {name!r} not found in catalog version {version}",
            ) from None
