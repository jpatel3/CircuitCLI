"""Plaid financial integration — sync transactions, balances, and recurring bills."""

from __future__ import annotations

import json
from typing import Any

from circuitai.core.config import load_config, update_config
from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError
from circuitai.models.base import new_id, now_iso

try:
    import plaid
    from plaid.api import plaid_api
    from plaid.model.country_code import CountryCode
    from plaid.model.link_token_create_request import LinkTokenCreateRequest
    from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
    from plaid.model.item_public_token_exchange_request import ItemPublicTokenExchangeRequest
    from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
    from plaid.model.transactions_sync_request import TransactionsSyncRequest
    from plaid.model.transactions_recurring_get_request import TransactionsRecurringGetRequest
    from plaid.model.products import Products
    from plaid.model.identity_get_request import IdentityGetRequest

    HAS_PLAID = True
except ImportError:
    HAS_PLAID = False

_PLAID_ENVS = {
    "sandbox": "sandbox",
    "development": "development",
    "production": "production",
}


class PlaidService:
    """Core Plaid integration logic — credentials, linking, syncing."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self._client: Any = None

    # ── Helpers ──────────────────────────────────────────────────────

    def _require_plaid(self) -> None:
        if not HAS_PLAID:
            raise AdapterError("plaid-python is not installed. Install with: pip install circuitai[plaid]")

    def _get_client(self) -> Any:
        """Build or return a cached plaid_api.PlaidApi client."""
        if self._client is not None:
            return self._client

        self._require_plaid()
        config = load_config()
        plaid_cfg = config.get("plaid", {})
        client_id = plaid_cfg.get("client_id", "")
        env = plaid_cfg.get("environment", "sandbox")

        row = self.db.fetchone(
            "SELECT value FROM adapter_state WHERE adapter_name = 'plaid' AND key = 'client_secret'"
        )
        if not row or not client_id:
            raise AdapterError("Plaid not configured. Run 'circuit plaid setup' first.")
        secret = row["value"]

        host = getattr(plaid.Environment, env.capitalize(), plaid.Environment.Sandbox)
        configuration = plaid.Configuration(
            host=host,
            api_key={"clientId": client_id, "secret": secret},
        )
        api_client = plaid.ApiClient(configuration)
        self._client = plaid_api.PlaidApi(api_client)
        return self._client

    def _get_state(self, key: str) -> str | None:
        row = self.db.fetchone(
            "SELECT value FROM adapter_state WHERE adapter_name = 'plaid' AND key = ?",
            (key,),
        )
        return row["value"] if row else None

    def _set_state(self, key: str, value: str) -> None:
        self.db.execute(
            """INSERT INTO adapter_state (id, adapter_name, key, value, updated_at)
               VALUES (?, 'plaid', ?, ?, ?)
               ON CONFLICT(adapter_name, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
            (new_id(), key, value, now_iso()),
        )
        self.db.commit()

    # ── Credentials ──────────────────────────────────────────────────

    def save_credentials(self, client_id: str, secret: str, environment: str = "sandbox") -> None:
        """Persist Plaid credentials — TOML for non-sensitive, DB for secret."""
        if environment not in _PLAID_ENVS:
            raise AdapterError(f"Invalid environment: {environment}. Must be one of {list(_PLAID_ENVS)}")
        update_config(plaid={"client_id": client_id, "environment": environment})
        self._set_state("client_secret", secret)

    def is_configured(self) -> bool:
        config = load_config()
        plaid_cfg = config.get("plaid", {})
        if not plaid_cfg.get("client_id"):
            return False
        row = self.db.fetchone(
            "SELECT value FROM adapter_state WHERE adapter_name = 'plaid' AND key = 'client_secret'"
        )
        return bool(row and row["value"])

    # ── Link flow ────────────────────────────────────────────────────

    def create_link_token(self) -> str:
        """Create a Plaid Link token for the browser flow."""
        client = self._get_client()
        request = LinkTokenCreateRequest(
            user=LinkTokenCreateRequestUser(client_user_id="circuitai-user"),
            client_name="CircuitAI",
            products=[Products("transactions")],
            country_codes=[CountryCode("US")],
            language="en",
        )
        response = client.link_token_create(request)
        return response["link_token"]

    def exchange_public_token(self, public_token: str, metadata: dict[str, Any] | None = None) -> str:
        """Exchange a public token for an access token and store the item."""
        client = self._get_client()
        request = ItemPublicTokenExchangeRequest(public_token=public_token)
        response = client.item_public_token_exchange(request)
        access_token = response["access_token"]
        item_id = response["item_id"]

        institution = ""
        if metadata and metadata.get("institution"):
            institution = metadata["institution"].get("name", "")

        item_data = json.dumps({
            "access_token": access_token,
            "item_id": item_id,
            "institution": institution,
        })
        self._set_state(f"item_{item_id}", item_data)

        # Map accounts from link metadata
        if metadata and metadata.get("accounts"):
            for acct in metadata["accounts"]:
                self._map_or_create_account(acct, institution)

        return item_id

    # ── Sync ─────────────────────────────────────────────────────────

    def sync_all(self) -> dict[str, Any]:
        """Run a full incremental sync across all connected items."""
        items = self._get_all_items()
        if not items:
            raise AdapterError("No connected bank accounts. Run 'circuit plaid link' first.")

        totals: dict[str, int] = {"imported": 0, "updated": 0, "modified": 0, "removed": 0, "bills_created": 0}
        errors: list[str] = []

        for item in items:
            access_token = item["access_token"]
            item_id = item["item_id"]
            institution = item.get("institution", "")
            try:
                bal = self._sync_balances(access_token, institution)
                totals["updated"] += bal
                txn = self._sync_transactions_for_item(access_token, item_id, institution)
                totals["imported"] += txn.get("added", 0)
                totals["modified"] += txn.get("modified", 0)
                totals["removed"] += txn.get("removed", 0)
                bills = self._sync_recurring(access_token)
                totals["bills_created"] += bills
            except Exception as e:
                errors.append(f"{institution or item_id}: {e}")

        return {**totals, "errors": errors}

    def _get_all_items(self) -> list[dict[str, Any]]:
        rows = self.db.fetchall(
            "SELECT key, value FROM adapter_state WHERE adapter_name = 'plaid' AND key LIKE 'item_%'"
        )
        items = []
        for row in rows:
            try:
                items.append(json.loads(row["value"]))
            except json.JSONDecodeError:
                continue
        return items

    # ── Balances ─────────────────────────────────────────────────────

    def _sync_balances(self, access_token: str, institution: str) -> int:
        """Fetch current balances and update mapped accounts/cards."""
        client = self._get_client()
        request = AccountsBalanceGetRequest(access_token=access_token)
        response = client.accounts_balance_get(request)

        updated = 0
        for acct in response["accounts"]:
            plaid_acct_id = acct["account_id"]
            balance = acct.get("balances", {})
            current = balance.get("current")
            if current is None:
                continue

            mapping = self._get_account_mapping(plaid_acct_id)
            if not mapping:
                self._map_or_create_account(
                    {"id": plaid_acct_id, "name": acct.get("name", ""),
                     "mask": acct.get("mask", ""), "type": acct.get("type", ""),
                     "subtype": acct.get("subtype", "")},
                    institution,
                )
                mapping = self._get_account_mapping(plaid_acct_id)

            if not mapping:
                continue

            balance_cents = int(round(current * 100))
            entity_type = mapping["entity_type"]
            entity_id = mapping["entity_id"]

            if entity_type == "account":
                from circuitai.models.account import AccountRepository
                AccountRepository(self.db).update_balance(entity_id, balance_cents)
            elif entity_type == "card":
                from circuitai.models.card import CardRepository
                CardRepository(self.db).update_balance(entity_id, balance_cents)
            updated += 1

        return updated

    # ── Transactions ─────────────────────────────────────────────────

    def _sync_transactions_for_item(
        self, access_token: str, item_id: str, institution: str
    ) -> dict[str, int]:
        """Incremental transaction sync using /transactions/sync with cursor pagination."""
        client = self._get_client()
        cursor = self._get_state(f"cursor_{item_id}") or ""
        added_count = 0
        modified_count = 0
        removed_count = 0
        has_more = True

        while has_more:
            request = TransactionsSyncRequest(access_token=access_token, cursor=cursor)
            response = client.transactions_sync(request)

            for txn in response.get("added", []):
                self._upsert_transaction(txn, institution)
                added_count += 1

            for txn in response.get("modified", []):
                self._upsert_transaction(txn, institution)
                modified_count += 1

            for txn in response.get("removed", []):
                self._remove_transaction(txn.get("transaction_id", ""))
                removed_count += 1

            cursor = response.get("next_cursor", "")
            has_more = response.get("has_more", False)

        if cursor:
            self._set_state(f"cursor_{item_id}", cursor)

        return {"added": added_count, "modified": modified_count, "removed": removed_count}

    def _upsert_transaction(self, txn: Any, institution: str) -> None:
        """Map a Plaid transaction to account_transactions or card_transactions.

        Plaid sign convention: positive = money leaving the account (debit).
        CircuitAI sign convention: negative = debit, positive = credit.
        So we flip: amount_cents = -int(round(plaid_amount * 100))
        """
        plaid_txn_id = txn.get("transaction_id", "")
        plaid_acct_id = txn.get("account_id", "")
        description = txn.get("name", "") or txn.get("merchant_name", "") or "Unknown"
        plaid_amount = txn.get("amount", 0)
        amount_cents = -int(round(plaid_amount * 100))
        txn_date = txn.get("date", "") or txn.get("authorized_date", "") or now_iso()[:10]
        category_list = txn.get("category") or []
        category = category_list[0] if category_list else ""

        mapping = self._get_account_mapping(plaid_acct_id)
        if not mapping:
            self._map_or_create_account(
                {"id": plaid_acct_id, "name": "", "mask": "", "type": "depository", "subtype": "checking"},
                institution,
            )
            mapping = self._get_account_mapping(plaid_acct_id)
        if not mapping:
            return

        entity_type = mapping["entity_type"]
        entity_id = mapping["entity_id"]

        if entity_type == "account":
            existing = self.db.fetchone(
                "SELECT id FROM account_transactions WHERE plaid_txn_id = ?", (plaid_txn_id,)
            )
            if existing:
                self.db.execute(
                    """UPDATE account_transactions
                       SET description = ?, amount_cents = ?, transaction_date = ?, category = ?
                       WHERE plaid_txn_id = ?""",
                    (description, amount_cents, str(txn_date), category, plaid_txn_id),
                )
            else:
                self.db.execute(
                    """INSERT INTO account_transactions
                       (id, account_id, description, amount_cents, transaction_date, category, plaid_txn_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (new_id(), entity_id, description, amount_cents, str(txn_date), category, plaid_txn_id, now_iso()),
                )
        elif entity_type == "card":
            existing = self.db.fetchone(
                "SELECT id FROM card_transactions WHERE plaid_txn_id = ?", (plaid_txn_id,)
            )
            if existing:
                self.db.execute(
                    """UPDATE card_transactions
                       SET description = ?, amount_cents = ?, transaction_date = ?, category = ?
                       WHERE plaid_txn_id = ?""",
                    (description, amount_cents, str(txn_date), category, plaid_txn_id),
                )
            else:
                self.db.execute(
                    """INSERT INTO card_transactions
                       (id, card_id, description, amount_cents, transaction_date, category, plaid_txn_id, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (new_id(), entity_id, description, amount_cents, str(txn_date), category, plaid_txn_id, now_iso()),
                )

        self.db.commit()

    def _remove_transaction(self, plaid_txn_id: str) -> None:
        """Remove a transaction that Plaid reports as removed."""
        if not plaid_txn_id:
            return
        self.db.execute("DELETE FROM account_transactions WHERE plaid_txn_id = ?", (plaid_txn_id,))
        self.db.execute("DELETE FROM card_transactions WHERE plaid_txn_id = ?", (plaid_txn_id,))
        self.db.commit()

    # ── Recurring / Bills ────────────────────────────────────────────

    def _sync_recurring(self, access_token: str) -> int:
        """Detect recurring transactions and create bills."""
        client = self._get_client()
        request = TransactionsRecurringGetRequest(access_token=access_token)
        response = client.transactions_recurring_get(request)

        created = 0
        outflow_streams = response.get("outflow_streams", [])

        for stream in outflow_streams:
            if not stream.get("is_active", False):
                continue

            stream_id = stream.get("stream_id", "")
            seen_key = f"recurring_{stream_id}"
            if self._get_state(seen_key):
                continue  # Already processed

            merchant = stream.get("merchant_name", "") or stream.get("description", "Unknown")
            plaid_amount = stream.get("last_amount", {}).get("amount", 0)
            amount_cents = abs(int(round(plaid_amount * 100)))
            frequency = stream.get("frequency", "MONTHLY").lower()
            if frequency not in ("monthly", "weekly", "biweekly", "yearly", "quarterly"):
                frequency = "monthly"

            last_date = stream.get("last_date", "")
            due_day = None
            if last_date:
                try:
                    due_day = int(str(last_date).split("-")[2])
                except (IndexError, ValueError):
                    pass

            from circuitai.services.bill_service import BillService
            svc = BillService(self.db)
            bill = svc.add_bill(
                name=merchant,
                provider=merchant,
                category=stream.get("category", ["other"])[0] if stream.get("category") else "other",
                amount_cents=amount_cents,
                due_day=due_day,
                frequency=frequency,
            )
            # Add match pattern for statement linking
            if merchant:
                bill.add_pattern(merchant.upper())
                from circuitai.models.bill import BillRepository
                BillRepository(self.db).update(bill.id, match_patterns=bill.match_patterns)

            self._set_state(seen_key, json.dumps({"bill_id": bill.id, "stream_id": stream_id}))
            created += 1

        return created

    # ── Identity ─────────────────────────────────────────────────────

    def fetch_identity(self, item_id: str) -> dict[str, Any]:
        """Fetch account holder identity information."""
        item_data = self._get_state(f"item_{item_id}")
        if not item_data:
            raise AdapterError(f"Item not found: {item_id}")
        item = json.loads(item_data)
        access_token = item["access_token"]

        client = self._get_client()
        request = IdentityGetRequest(access_token=access_token)
        response = client.identity_get(request)

        accounts_info = []
        for acct in response.get("accounts", []):
            owners = []
            for owner in acct.get("owners", []):
                owners.append({
                    "names": owner.get("names", []),
                    "emails": [e.get("data", "") for e in owner.get("emails", [])],
                    "phones": [p.get("data", "") for p in owner.get("phone_numbers", [])],
                    "addresses": [
                        a.get("data", {}).get("street", "") for a in owner.get("addresses", [])
                    ],
                })
            accounts_info.append({
                "name": acct.get("name", ""),
                "mask": acct.get("mask", ""),
                "owners": owners,
            })

        return {"item_id": item_id, "institution": item.get("institution", ""), "accounts": accounts_info}

    # ── Account mapping ──────────────────────────────────────────────

    def _get_account_mapping(self, plaid_account_id: str) -> dict[str, str] | None:
        row = self.db.fetchone(
            "SELECT entity_type, entity_id FROM plaid_account_map WHERE plaid_account_id = ?",
            (plaid_account_id,),
        )
        if not row:
            return None
        return {"entity_type": row["entity_type"], "entity_id": row["entity_id"]}

    def _map_or_create_account(self, plaid_acct: dict[str, Any], institution: str) -> None:
        """Check plaid_account_map; if not found, auto-create an Account or Card."""
        plaid_acct_id = plaid_acct.get("id", "")
        if not plaid_acct_id:
            return

        existing = self._get_account_mapping(plaid_acct_id)
        if existing:
            return

        acct_type = plaid_acct.get("type", "depository")
        subtype = plaid_acct.get("subtype", "")
        name = plaid_acct.get("name", "") or f"{institution} Account"
        mask = plaid_acct.get("mask", "")

        if acct_type == "credit" or subtype == "credit card":
            # Create a Card
            from circuitai.models.card import Card, CardRepository
            card = Card(name=name, institution=institution, last_four=mask)
            CardRepository(self.db).insert(card)
            entity_type, entity_id = "card", card.id
        else:
            # Create an Account (checking, savings, etc.)
            from circuitai.models.account import Account, AccountRepository
            mapped_type = "checking"
            if subtype in ("savings", "money market", "cd"):
                mapped_type = "savings"
            acct = Account(name=name, institution=institution, account_type=mapped_type, last_four=mask)
            AccountRepository(self.db).insert(acct)
            entity_type, entity_id = "account", acct.id

        self.db.execute(
            """INSERT INTO plaid_account_map
               (id, plaid_account_id, entity_type, entity_id, institution, plaid_name, plaid_mask, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_id(), plaid_acct_id, entity_type, entity_id, institution, name, mask, now_iso()),
        )
        self.db.commit()

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict[str, Any]:
        """Return status of all connected Plaid items."""
        items = self._get_all_items()
        result: list[dict[str, Any]] = []
        for item in items:
            item_id = item["item_id"]
            cursor = self._get_state(f"cursor_{item_id}") or ""
            result.append({
                "item_id": item_id,
                "institution": item.get("institution", ""),
                "has_cursor": bool(cursor),
            })
        return {"configured": self.is_configured(), "items": result}
