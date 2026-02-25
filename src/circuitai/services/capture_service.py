"""Screen capture service — screenshot bank pages, extract via vision API, import with dedup."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError
from circuitai.models.base import new_id, now_iso

try:
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False


def compute_txn_fingerprint(txn_date: str, description: str, amount_cents: int) -> str:
    """Compute a deterministic fingerprint for dedup across import sources.

    Normalizes description to uppercase alphanumeric only, then hashes
    date|description|amount. Returns first 16 hex chars of SHA-256.
    """
    normalized = re.sub(r"[^A-Z0-9]", "", description.upper())
    raw = f"{txn_date}|{normalized}|{amount_cents}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


_EXTRACTION_PROMPT = """\
You are extracting financial data from a screenshot of a bank or credit card website.

Return ONLY valid JSON (no markdown fences) with this structure:
{
  "account_name": "string or null",
  "account_type": "checking" | "savings" | "credit_card" | "unknown",
  "balance_cents": integer or null,
  "transactions": [
    {
      "date": "YYYY-MM-DD",
      "description": "string",
      "amount_cents": integer,
      "category": "string or empty"
    }
  ]
}

Rules:
- All monetary amounts in cents (e.g., $42.50 → 4250)
- Debits/charges are NEGATIVE, credits/deposits are POSITIVE
- Dates as YYYY-MM-DD
- If you can't determine a field, use null
- If no transactions visible, return empty transactions array
"""


class CaptureService:
    """Screenshot bank pages, extract transactions via Claude vision, import with dedup."""

    ADAPTER_NAME = "capture"

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db

    # ── Adapter state helpers ────────────────────────────────────────

    def _get_state(self, key: str) -> str | None:
        row = self.db.fetchone(
            "SELECT value FROM adapter_state WHERE adapter_name = ? AND key = ?",
            (self.ADAPTER_NAME, key),
        )
        return row["value"] if row else None

    def _set_state(self, key: str, value: str) -> None:
        self.db.execute(
            """INSERT INTO adapter_state (id, adapter_name, key, value, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(adapter_name, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (new_id(), self.ADAPTER_NAME, key, value, now_iso()),
        )
        self.db.commit()

    # ── Credentials ──────────────────────────────────────────────────

    def save_api_key(self, key: str) -> None:
        """Store Anthropic API key in adapter_state (encrypted at rest via SQLCipher)."""
        self._set_state("anthropic_api_key", key)

    def is_configured(self) -> bool:
        """Check if an Anthropic API key is stored."""
        val = self._get_state("anthropic_api_key")
        return bool(val)

    def _get_api_key(self) -> str:
        val = self._get_state("anthropic_api_key")
        if not val:
            raise AdapterError("Anthropic API key not configured. Run 'circuit capture setup' first.")
        return val

    # ── Screenshot ───────────────────────────────────────────────────

    def take_screenshot(self) -> Path:
        """Take an interactive window screenshot (macOS only). Returns path to temp PNG."""
        if sys.platform != "darwin":
            raise AdapterError("Screen capture is only supported on macOS.")

        tmp = Path(tempfile.mktemp(suffix=".png"))
        result = subprocess.run(
            ["screencapture", "-iW", str(tmp)],
            capture_output=True,
        )
        if result.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
            tmp.unlink(missing_ok=True)
            raise AdapterError("Screenshot cancelled or failed.")
        return tmp

    # ── Vision extraction ────────────────────────────────────────────

    def extract_from_screenshot(self, image_path: Path) -> dict[str, Any]:
        """Send screenshot to Claude Haiku 4.5 vision API and parse the result."""
        if not HAS_ANTHROPIC:
            raise AdapterError("anthropic package not installed. Install with: pip install circuitai[capture]")

        api_key = self._get_api_key()
        image_data = base64.b64encode(image_path.read_bytes()).decode("utf-8")

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": _EXTRACTION_PROMPT,
                        },
                    ],
                }
            ],
        )

        raw = message.content[0].text.strip()
        # Handle potential ```json wrapping
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise AdapterError(f"Vision API returned invalid JSON: {e}\nRaw: {raw[:200]}") from e

    # ── Import with dedup ────────────────────────────────────────────

    def import_transactions(
        self,
        data: dict[str, Any],
        account_id: str,
        entity_type: str = "account",
    ) -> dict[str, Any]:
        """Import extracted transactions with fingerprint-based dedup.

        Returns: {imported, skipped, errors, balance_updated}
        """
        imported = 0
        skipped = 0
        errors: list[str] = []
        balance_updated = False

        transactions = data.get("transactions", [])
        table = "account_transactions" if entity_type == "account" else "card_transactions"
        fk_col = "account_id" if entity_type == "account" else "card_id"

        for i, txn in enumerate(transactions):
            try:
                txn_date = txn.get("date", "")
                description = txn.get("description", "")
                amount_cents = int(txn.get("amount_cents", 0))
                category = txn.get("category", "")

                if not txn_date or not description:
                    errors.append(f"Transaction {i}: missing date or description")
                    continue

                fingerprint = compute_txn_fingerprint(txn_date, description, amount_cents)

                # Check for existing fingerprint in BOTH tables for cross-source dedup
                existing_acct = self.db.fetchone(
                    "SELECT id FROM account_transactions WHERE txn_fingerprint = ?",
                    (fingerprint,),
                )
                existing_card = self.db.fetchone(
                    "SELECT id FROM card_transactions WHERE txn_fingerprint = ?",
                    (fingerprint,),
                )
                if existing_acct or existing_card:
                    skipped += 1
                    continue

                self.db.execute(
                    f"""INSERT INTO {table}
                       (id, {fk_col}, description, amount_cents, transaction_date, category, txn_fingerprint, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (new_id(), account_id, description, amount_cents, txn_date, category, fingerprint, now_iso()),
                )
                imported += 1
            except Exception as e:
                errors.append(f"Transaction {i}: {e}")

        if imported:
            self.db.commit()

        # Update balance if provided
        balance_cents = data.get("balance_cents")
        if balance_cents is not None:
            try:
                if entity_type == "account":
                    from circuitai.models.account import AccountRepository
                    AccountRepository(self.db).update_balance(account_id, balance_cents)
                else:
                    from circuitai.models.card import CardRepository
                    CardRepository(self.db).update_balance(account_id, balance_cents)
                balance_updated = True
            except Exception as e:
                errors.append(f"Balance update failed: {e}")

        return {
            "imported": imported,
            "skipped": skipped,
            "errors": errors,
            "balance_updated": balance_updated,
        }

    # ── Statement linking ────────────────────────────────────────────

    def run_statement_linking(self, account_id: str) -> dict[str, Any]:
        """Delegate to StatementLinker for bill matching."""
        from circuitai.services.statement_linker import StatementLinker
        linker = StatementLinker(self.db)
        return linker.link_transactions(account_id)

    # ── Orchestrator ─────────────────────────────────────────────────

    def snap(self, account_id: str, entity_type: str = "account") -> dict[str, Any]:
        """Full flow: screenshot → extract → import → link."""
        screenshot_path = self.take_screenshot()
        try:
            data = self.extract_from_screenshot(screenshot_path)
            result = self.import_transactions(data, account_id, entity_type)
            if result["imported"] > 0:
                link_result = self.run_statement_linking(account_id)
                result["linked"] = link_result.get("matched", 0)
            else:
                result["linked"] = 0
            return result
        finally:
            screenshot_path.unlink(missing_ok=True)
