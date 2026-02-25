"""Built-in manual entry adapter — for CLI-entered data."""

from __future__ import annotations

from typing import Any

from circuitai.adapters.base import BaseAdapter
from circuitai.core.database import DatabaseConnection


class ManualAdapter(BaseAdapter):
    """Adapter for manually entered data (no-op sync)."""

    def metadata(self) -> dict[str, str]:
        return {
            "name": "manual",
            "version": "0.1.0",
            "description": "Manual data entry via CLI commands",
            "author": "CircuitAI",
        }

    def sync(self, db: DatabaseConnection) -> dict[str, Any]:
        # Manual adapter doesn't sync — data is entered directly
        return {"status": "ok", "message": "Manual adapter: no sync needed."}
