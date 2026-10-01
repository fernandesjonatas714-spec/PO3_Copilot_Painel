"""Persistência isolada dos dados históricos da V2."""

from .migrations import CURRENT_SCHEMA_VERSION, migrate

__all__ = ["CURRENT_SCHEMA_VERSION", "migrate"]
