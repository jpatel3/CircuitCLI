"""Built-in PDF import adapter — extracts transactions or bill info from PDF statements."""

from __future__ import annotations

import os
import re
from typing import Any

from circuitai.adapters.base import BaseAdapter
from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


class PdfImportAdapter(BaseAdapter):
    """Imports transaction data or extracts bill info from PDF statements."""

    def __init__(self) -> None:
        self._file_path: str | None = None
        self._account_id: str | None = None
        self._mode: str = "transactions"  # "transactions" or "bill-info"

    def metadata(self) -> dict[str, str]:
        return {
            "name": "pdf-import",
            "version": "0.1.0",
            "description": "Import transactions or extract bill info from PDF statements",
            "author": "CircuitAI",
        }

    def configure(self) -> None:
        """Interactively configure the PDF import."""
        if not HAS_PDFPLUMBER:
            raise AdapterError("pdfplumber is not installed. Install with: pip install circuitai[pdf]")

        import click

        self._file_path = click.prompt("PDF file path")
        if not os.path.exists(self._file_path):
            raise AdapterError(f"File not found: {self._file_path}")

        self._mode = click.prompt(
            "Import mode",
            type=click.Choice(["transactions", "bill-info"]),
            default="transactions",
        )
        if self._mode == "transactions":
            self._account_id = click.prompt("Account ID to import into")

    def configure_for_file(
        self,
        file_path: str,
        account_id: str | None = None,
        mode: str = "transactions",
    ) -> None:
        """Non-interactive configuration for REPL file-drop usage."""
        if not HAS_PDFPLUMBER:
            raise AdapterError("pdfplumber is not installed. Install with: pip install circuitai[pdf]")
        if not os.path.exists(file_path):
            raise AdapterError(f"File not found: {file_path}")
        self._file_path = file_path
        self._account_id = account_id
        self._mode = mode

    def validate_config(self) -> bool:
        if not self._file_path or not os.path.exists(self._file_path):
            return False
        if self._mode == "transactions" and not self._account_id:
            return False
        return True

    def sync(self, db: DatabaseConnection) -> dict[str, Any]:
        """Extract data from the PDF file."""
        if not HAS_PDFPLUMBER:
            raise AdapterError("pdfplumber is not installed. Install with: pip install circuitai[pdf]")
        if not self.validate_config():
            raise AdapterError("PDF import not configured. Run configure() first.")

        if self._mode == "bill-info":
            return self._extract_bill_info()
        return self._extract_transactions(db)

    def _extract_transactions(self, db: DatabaseConnection) -> dict[str, Any]:
        """Extract tabular transaction data from PDF and insert into account_transactions."""
        imported = 0
        errors: list[str] = []

        try:
            with pdfplumber.open(self._file_path) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    tables = page.extract_tables()
                    for table in tables:
                        if not table or len(table) < 2:
                            continue

                        # Use first row as headers
                        headers = [str(h).strip().lower() if h else "" for h in table[0]]
                        date_idx = self._find_column(headers, ["date", "trans date", "transaction date", "posted"])
                        desc_idx = self._find_column(headers, ["description", "memo", "details", "transaction"])
                        amt_idx = self._find_column(headers, ["amount", "debit", "credit", "total"])

                        if date_idx is None or desc_idx is None or amt_idx is None:
                            continue

                        for row_num, row in enumerate(table[1:], start=2):
                            try:
                                txn_date = str(row[date_idx]).strip() if row[date_idx] else ""
                                description = str(row[desc_idx]).strip() if row[desc_idx] else ""
                                amount_str = str(row[amt_idx]).strip() if row[amt_idx] else "0"

                                if not txn_date or not description:
                                    continue

                                # Parse amount
                                amount_str = amount_str.replace(",", "").replace("$", "").strip()
                                if amount_str.startswith("(") and amount_str.endswith(")"):
                                    amount_str = "-" + amount_str[1:-1]
                                if not amount_str or amount_str == "-":
                                    continue
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
                                errors.append(f"Page {page_num}, row {row_num}: {e}")

            db.commit()
        except Exception as e:
            raise AdapterError(f"PDF import failed: {e}") from e

        return {"imported": imported, "errors": errors}

    def _extract_bill_info(self) -> dict[str, Any]:
        """Extract amount due and due date from PDF text using regex patterns."""
        full_text = ""
        try:
            with pdfplumber.open(self._file_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        full_text += page_text + "\n"
        except Exception as e:
            raise AdapterError(f"PDF read failed: {e}") from e

        if not full_text.strip():
            return {"amount_due": None, "due_date": None, "raw_text_length": 0}

        # Extract amount due
        amount_due = None
        amount_patterns = [
            r"(?:amount\s+due|total\s+due|balance\s+due|minimum\s+due|new\s+balance)[:\s]*\$?([\d,]+\.?\d*)",
            r"\$\s*([\d,]+\.\d{2})\s*(?:due|owed|owing)",
        ]
        for pattern in amount_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                amount_str = match.group(1).replace(",", "")
                amount_due = int(float(amount_str) * 100)
                break

        # Extract due date
        due_date = None
        date_patterns = [
            r"(?:due\s+date|payment\s+due)[:\s]*([\d]{1,2}[/\-][\d]{1,2}[/\-][\d]{2,4})",
            r"(?:due\s+(?:by|on|before))[:\s]*((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\w*\s+\d{1,2},?\s*\d{2,4})",
        ]
        for pattern in date_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                due_date = match.group(1).strip()
                break

        return {
            "amount_due": amount_due,
            "due_date": due_date,
            "raw_text_length": len(full_text),
        }

    @staticmethod
    def _find_column(headers: list[str], candidates: list[str]) -> int | None:
        """Find the index of the first header matching any candidate."""
        for i, header in enumerate(headers):
            for candidate in candidates:
                if candidate in header:
                    return i
        return None

    def test_connection(self) -> bool:
        return bool(self._file_path and os.path.exists(self._file_path))
