"""Browser automation service — Playwright lifecycle, keyring credentials, and bill import."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import keyring

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError
from circuitai.services.capture_service import compute_txn_fingerprint

try:
    from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

    HAS_PLAYWRIGHT = True
except ImportError:
    HAS_PLAYWRIGHT = False

KEYRING_SERVICE_PREFIX = "circuitai"
BROWSER_DATA_DIR = Path.home() / ".circuitai" / "browser_data"


class BrowserService:
    """Manages Playwright browser lifecycle and keyring-based credentials."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self._playwright = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None

    # ── Credential management via keyring ────────────────────────────

    @staticmethod
    def _keyring_service(site_key: str) -> str:
        return f"{KEYRING_SERVICE_PREFIX}:{site_key}"

    def save_credentials(self, site_key: str, username: str, password: str) -> None:
        """Store site credentials in the system keychain."""
        service = self._keyring_service(site_key)
        # Store username under a known key, password under the username
        keyring.set_password(service, "_username", username)
        keyring.set_password(service, username, password)

    def get_credentials(self, site_key: str) -> tuple[str, str] | None:
        """Retrieve credentials from the system keychain. Returns (username, password) or None."""
        service = self._keyring_service(site_key)
        username = keyring.get_password(service, "_username")
        if not username:
            return None
        password = keyring.get_password(service, username)
        if not password:
            return None
        return (username, password)

    def has_credentials(self, site_key: str) -> bool:
        """Check if credentials exist for a site."""
        return self.get_credentials(site_key) is not None

    def delete_credentials(self, site_key: str) -> None:
        """Remove credentials for a site from the keychain."""
        service = self._keyring_service(site_key)
        username = keyring.get_password(service, "_username")
        if username:
            try:
                keyring.delete_password(service, username)
            except keyring.errors.PasswordDeleteError:
                pass
            try:
                keyring.delete_password(service, "_username")
            except keyring.errors.PasswordDeleteError:
                pass

    # ── Playwright lifecycle ─────────────────────────────────────────

    def launch_browser(self) -> tuple[Any, Any, Any]:
        """Launch a visible Chromium browser with persistent context.

        Returns (browser, context, page).
        Uses persistent context at ~/.circuitai/browser_data/ for cookie persistence.
        """
        if not HAS_PLAYWRIGHT:
            raise AdapterError(
                "playwright package not installed. Install with: pip install circuitai[browser]\n"
                "Then run: playwright install chromium"
            )

        BROWSER_DATA_DIR.mkdir(parents=True, exist_ok=True)

        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_DATA_DIR),
            headless=False,
            viewport={"width": 1280, "height": 900},
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()

        return (self._context, self._context, self._page)

    def close_browser(self) -> None:
        """Clean up browser resources."""
        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None
        self._page = None

    # ── Import helper ────────────────────────────────────────────────

    def import_bill_data(self, site_key: str, data: dict[str, Any]) -> dict[str, Any]:
        """Import extracted billing data as bill payments with fingerprint dedup.

        Args:
            site_key: Site identifier (e.g. "jcpl")
            data: Extracted billing data with keys:
                - account_name: str
                - current_balance_cents: int
                - bills: list of {date, amount_cents, description}
                - category: str (optional, defaults to site's BILL_CATEGORY)

        Returns:
            {bill_name, amount_cents, imported, skipped}
        """
        from circuitai.services.bill_service import BillService

        bill_svc = BillService(self.db)
        account_name = data.get("account_name", site_key.upper())
        category = data.get("category", "other")
        bills = data.get("bills", [])

        # Find or create the bill
        existing = bill_svc.search_bills(account_name)
        if existing:
            bill = existing[0]
        else:
            bill = bill_svc.add_bill(
                name=account_name,
                provider=account_name,
                category=category,
                amount_cents=data.get("current_balance_cents", 0),
            )

        # Update the bill amount to current balance if available
        balance = data.get("current_balance_cents")
        if balance is not None and balance != bill.amount_cents:
            bill_svc.update_bill(bill.id, amount_cents=balance)

        imported = 0
        skipped = 0

        for bill_entry in bills:
            txn_date = bill_entry.get("date", "")
            amount_cents = bill_entry.get("amount_cents", 0)
            description = bill_entry.get("description", account_name)

            if not txn_date or not amount_cents:
                continue

            fingerprint = compute_txn_fingerprint(txn_date, description, amount_cents)

            # Check if this payment already exists (dedup via fingerprint in notes)
            existing_payments = bill_svc.get_payments(bill.id, limit=100)
            already_exists = any(
                p.notes and fingerprint in p.notes for p in existing_payments
            )
            if already_exists:
                skipped += 1
                continue

            bill_svc.pay_bill(
                bill_id=bill.id,
                amount_cents=amount_cents,
                paid_date=txn_date,
                notes=f"browser-import:{fingerprint}",
            )
            imported += 1

        return {
            "bill_name": bill.name,
            "amount_cents": balance or bill.amount_cents,
            "imported": imported,
            "skipped": skipped,
        }
