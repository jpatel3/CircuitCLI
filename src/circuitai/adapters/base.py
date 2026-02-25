"""Base adapter — convenience ABC implementing the protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from circuitai.core.database import DatabaseConnection


class BaseAdapter(ABC):
    """Abstract base class for adapters. Provides default implementations."""

    @abstractmethod
    def metadata(self) -> dict[str, str]:
        ...

    def configure(self) -> None:
        """Override to add interactive configuration."""
        pass

    def validate_config(self) -> bool:
        """Override to validate configuration."""
        return True

    @abstractmethod
    def sync(self, db: DatabaseConnection) -> dict[str, Any]:
        ...

    def test_connection(self) -> bool:
        """Override to test external connection."""
        return True
