"""Stable error codes and exception type for the physical quantity engine."""

from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    """Stable, machine-readable error codes."""

    PARSE_ERROR = "PARSE_ERROR"
    UNKNOWN_QUANTITY = "UNKNOWN_QUANTITY"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    UNIT_CONVERSION_FAILED = "UNIT_CONVERSION_FAILED"
    DOMAIN_ERROR = "DOMAIN_ERROR"
    DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    OVERFLOW = "OVERFLOW"
    UNCERTAINTY_INVALID = "UNCERTAINTY_INVALID"
    VERSION_NOT_FOUND = "VERSION_NOT_FOUND"
    CATALOG_CONFLICT = "CATALOG_CONFLICT"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    TASK_CANCELLED = "TASK_CANCELLED"
    TASK_FAILED = "TASK_FAILED"
    INVALID_REQUEST = "INVALID_REQUEST"


class EngineError(Exception):
    """Deterministic engine error carrying a stable code and message."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code.value, "message": self.message}
