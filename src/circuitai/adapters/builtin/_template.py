"""Template adapter — copy this file to create a new CircuitAI integration.

How to create a new adapter:

1. Copy this file to a new module (e.g., `my_bank.py`)
2. Implement all methods marked with TODO
3. Register your adapter in pyproject.toml:

   [project.entry-points."circuitai.adapters"]
   my-bank = "circuitai.adapters.builtin.my_bank:MyBankAdapter"

4. Reinstall: `pip install -e .`
5. Verify: `circuit integrations` should list your adapter

References:
  - Protocol definition:  src/circuitai/adapters/protocol.py
  - Base class:           src/circuitai/adapters/base.py
  - Example (simple):     src/circuitai/adapters/builtin/manual.py
  - Example (full):       src/circuitai/adapters/builtin/csv_import.py
"""

from __future__ import annotations

from typing import Any

from circuitai.adapters.base import BaseAdapter
from circuitai.core.database import DatabaseConnection


class TemplateAdapter(BaseAdapter):
    """A template adapter — replace this docstring with your adapter's purpose."""

    def __init__(self) -> None:
        # TODO: Add any instance state your adapter needs (API keys, file paths, etc.)
        self._configured = False

    def metadata(self) -> dict[str, str]:
        """Return adapter metadata. All fields are required."""
        # TODO: Update these values for your adapter
        return {
            "name": "template",
            "version": "0.1.0",
            "description": "Template adapter — replace with your description",
            "author": "Your Name",
        }

    def configure(self) -> None:
        """Interactive configuration — prompt the user for credentials or settings.

        This is called by `circuit adapters configure <name>`.
        Use click.prompt() for interactive input.

        Example:
            import click
            self._api_key = click.prompt("API key", hide_input=True)
            self._account_id = click.prompt("Account ID")
            self._configured = True
        """
        # TODO: Implement interactive configuration
        pass

    def validate_config(self) -> bool:
        """Return True if the adapter is properly configured.

        Called before sync() to ensure prerequisites are met.

        Example:
            return bool(self._api_key and self._account_id)
        """
        # TODO: Validate your adapter's configuration
        return self._configured

    def sync(self, db: DatabaseConnection) -> dict[str, Any]:
        """Sync data from the external source into the CircuitAI database.

        This is the main entry point. Fetch data from your source, transform it,
        and insert it into the database using db.execute() and db.commit().

        Must return a dict with sync results:
            {"imported": int, "updated": int, "errors": list[str]}

        Example:
            from circuitai.models.base import new_id, now_iso

            imported = 0
            for record in self._fetch_from_api():
                db.execute(
                    "INSERT INTO account_transactions "
                    "(id, account_id, description, amount_cents, transaction_date, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id(), self._account_id, record["desc"],
                     int(record["amount"] * 100), record["date"], now_iso()),
                )
                imported += 1
            db.commit()
            return {"imported": imported, "updated": 0, "errors": []}
        """
        # TODO: Implement your sync logic
        return {"imported": 0, "updated": 0, "errors": []}

    def test_connection(self) -> bool:
        """Test whether the adapter can reach its data source.

        Called by `circuit adapters test <name>` to verify connectivity
        without actually syncing data.

        Example:
            try:
                response = requests.get(self._api_url, timeout=5)
                return response.status_code == 200
            except Exception:
                return False
        """
        # TODO: Implement connection test
        return False
