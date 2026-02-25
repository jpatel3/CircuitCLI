"""Adapter protocol — the contract all adapters must follow."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from circuitai.core.database import DatabaseConnection


@runtime_checkable
class CircuitAdapter(Protocol):
    """Protocol that all CircuitAI adapters must implement."""

    def metadata(self) -> dict[str, str]:
        """Return adapter metadata: name, version, description, author."""
        ...

    def configure(self) -> None:
        """Interactive configuration (prompts for credentials, settings, etc.)."""
        ...

    def validate_config(self) -> bool:
        """Validate the current configuration. Returns True if valid."""
        ...

    def sync(self, db: DatabaseConnection) -> dict[str, Any]:
        """Sync data from the external source into the CircuitAI database.

        Returns a dict with sync results: {"imported": int, "updated": int, "errors": list}
        """
        ...

    def test_connection(self) -> bool:
        """Test whether the adapter can connect to its data source."""
        ...
