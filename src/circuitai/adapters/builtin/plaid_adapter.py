"""Built-in Plaid adapter — syncs transactions, balances, and recurring bills."""

from __future__ import annotations

from typing import Any

from circuitai.adapters.base import BaseAdapter
from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError

try:
    import plaid  # noqa: F401

    HAS_PLAID = True
except ImportError:
    HAS_PLAID = False


class PlaidAdapter(BaseAdapter):
    """Adapter wrapper for Plaid financial data sync."""

    def metadata(self) -> dict[str, str]:
        return {
            "name": "plaid",
            "version": "0.1.0",
            "description": "Sync bank transactions, balances, and recurring bills via Plaid",
            "author": "CircuitAI",
        }

    def configure(self) -> None:
        """Redirect to the CLI setup command — Plaid Link requires a browser."""
        raise AdapterError(
            "Plaid requires browser-based setup. Run 'circuit plaid setup' "
            "followed by 'circuit plaid link' to connect your bank."
        )

    def validate_config(self) -> bool:
        if not HAS_PLAID:
            return False
        return True

    def sync(self, db: DatabaseConnection) -> dict[str, Any]:
        """Run a full incremental sync via PlaidService."""
        if not HAS_PLAID:
            raise AdapterError("plaid-python is not installed. Install with: pip install circuitai[plaid]")

        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        return svc.sync_all()

    def test_connection(self) -> bool:
        return HAS_PLAID
