"""Stable error codes and the single engine exception type."""
from __future__ import annotations

from enum import Enum


class ErrorCode(str, Enum):
    PARSE_ERROR = "PARSE_ERROR"
    UNKNOWN_NAME = "UNKNOWN_NAME"
    UNKNOWN_UNIT = "UNKNOWN_UNIT"
    DIMENSION_MISMATCH = "DIMENSION_MISMATCH"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    NON_FINITE_VALUE = "NON_FINITE_VALUE"
    OVERFLOW = "OVERFLOW"
    DIVISION_BY_ZERO = "DIVISION_BY_ZERO"
    UNIT_CONVERSION_FAILED = "UNIT_CONVERSION_FAILED"
    VERSION_NOT_FOUND = "VERSION_NOT_FOUND"
    CATALOG_CONFLICT = "CATALOG_CONFLICT"
    TASK_TIMEOUT = "TASK_TIMEOUT"
    TASK_CANCELLED = "TASK_CANCELLED"
    BATCH_NOT_FOUND = "BATCH_NOT_FOUND"
    INTERNAL_ERROR = "INTERNAL_ERROR"


class EngineError(Exception):
    """All domain failures are reported through this exception with a stable code."""

    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return f"{self.code.value}: {self.message}"

    def to_dict(self) -> dict:
        return {"error": {"code": self.code.value, "message": self.message}}
