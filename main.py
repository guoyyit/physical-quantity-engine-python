"""Backward-compatible entry point exposing the ASGI application."""
from pqe.__main__ import app  # noqa: F401

__all__ = ["app"]
