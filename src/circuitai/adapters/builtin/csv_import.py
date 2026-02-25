"""Built-in CSV import adapter — imports transactions from CSV files."""

from __future__ import annotations

import csv
import os
from typing import Any

import click

from circuitai.adapters.base import BaseAdapter
from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError


class CsvImportAdapter(BaseAdapter):
    """Imports transaction data from CSV files."""

    def __init__(self) -> None:
        self._file_path: str | None = None
        self._account_id: str | None = None
        self._date_column: str = "date"
        self._description_column: str = "description"
        self._amount_column: str = "amount"

    def metadata(self) -> dict[str, str]:
        return {
            "name": "csv-import",
            "version": "0.1.0",
            "description": "Import transactions from CSV files (bank/card statements)",
            "author": "CircuitAI",
        }

    def configure(self) -> None:
        """Interactively configure the CSV import."""
        self._file_path = click.prompt("CSV file path")
        if not os.path.exists(self._file_path):
            raise AdapterError(f"File not found: {self._file_path}")

        self._account_id = click.prompt("Account ID to import into")
        self._date_column = click.prompt("Date column name", default="date")
        self._description_column = click.prompt("Description column name", default="description")
        self._amount_column = click.prompt("Amount column name", default="amount")

    def configure_for_file(
        self,
        file_path: str,
        account_id: str,
        date_column: str = "date",
        description_column: str = "description",
        amount_column: str = "amount",
    ) -> None:
        """Non-interactive configuration for REPL file-drop usage."""
        if not os.path.exists(file_path):
            raise AdapterError(f"File not found: {file_path}")
        self._file_path = file_path
        self._account_id = account_id
        self._date_column = date_column
        self._description_column = description_column
        self._amount_column = amount_column

    def validate_config(self) -> bool:
        if not self._file_path or not os.path.exists(self._file_path):
            return False
        if not self._account_id:
            return False
        return True

    def sync(self, db: DatabaseConnection) -> dict[str, Any]:
        """Import transactions from the CSV file."""
        if not self.validate_config():
            raise AdapterError("CSV import not configured. Run configure() first.")

        imported = 0
        errors: list[str] = []

        try:
            with open(self._file_path, "r") as f:  # type: ignore[arg-type]
                reader = csv.DictReader(f)
                for row_num, row in enumerate(reader, start=2):
                    try:
                        txn_date = row.get(self._date_column, "")
                        description = row.get(self._description_column, "")
                        amount_str = row.get(self._amount_column, "0")

                        # Parse amount (handle negative, parentheses, commas)
                        amount_str = amount_str.replace(",", "").replace("$", "").strip()
                        if amount_str.startswith("(") and amount_str.endswith(")"):
                            amount_str = "-" + amount_str[1:-1]
                        amount_cents = int(float(amount_str) * 100)

                        from circuitai.models.base import new_id, now_iso
                        from circuitai.services.capture_service import compute_txn_fingerprint

                        fingerprint = compute_txn_fingerprint(txn_date, description, amount_cents)

                        # Dedup: skip if fingerprint already exists
                        existing = db.fetchone(
                            "SELECT id FROM account_transactions WHERE txn_fingerprint = ?",
                            (fingerprint,),
                        )
                        if existing:
                            continue

                        db.execute(
                            """INSERT INTO account_transactions
                               (id, account_id, description, amount_cents, transaction_date, txn_fingerprint, created_at)
                               VALUES (?, ?, ?, ?, ?, ?, ?)""",
                            (new_id(), self._account_id, description, amount_cents, txn_date, fingerprint, now_iso()),
                        )
                        imported += 1
                    except Exception as e:
                        errors.append(f"Row {row_num}: {e}")

            db.commit()

            # Run statement linking after import
            linked = self._run_statement_linking(db)

        except Exception as e:
            raise AdapterError(f"CSV import failed: {e}") from e

        return {
            "imported": imported,
            "linked": linked,
            "errors": errors,
        }

    def _run_statement_linking(self, db: DatabaseConnection) -> int:
        """Match imported transactions against known bills by description patterns."""
        import json

        linked = 0
        # Get all bills with match patterns
        bills = db.fetchall("SELECT id, match_patterns FROM bills WHERE is_active = 1")

        for bill in bills:
            patterns = json.loads(bill["match_patterns"])
            if not patterns:
                continue

            # Find unmatched transactions matching any pattern
            for pattern in patterns:
                matches = db.fetchall(
                    """SELECT id FROM account_transactions
                       WHERE is_matched = 0 AND UPPER(description) LIKE ?""",
                    (f"%{pattern.upper()}%",),
                )
                for match in matches:
                    db.execute(
                        "UPDATE account_transactions SET is_matched = 1, linked_bill_id = ? WHERE id = ?",
                        (bill["id"], match["id"]),
                    )
                    linked += 1

        if linked:
            db.commit()
        return linked

    def test_connection(self) -> bool:
        return bool(self._file_path and os.path.exists(self._file_path))
