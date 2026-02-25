"""Tests for Plaid integration — service, adapter, and link server."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test_plaid.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


# ── PlaidService tests ───────────────────────────────────────────


class TestPlaidCredentials:
    def test_save_and_check_configured(self, db):
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        assert not svc.is_configured()

        with patch("circuitai.services.plaid_service.update_config"):
            with patch("circuitai.services.plaid_service.load_config", return_value={
                "plaid": {"client_id": "test_id", "environment": "sandbox"}
            }):
                svc.save_credentials("test_id", "test_secret", "sandbox")
                assert svc.is_configured()

    def test_save_credentials_invalid_env(self, db):
        from circuitai.core.exceptions import AdapterError
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        with patch("circuitai.services.plaid_service.update_config"):
            with pytest.raises(AdapterError, match="Invalid environment"):
                svc.save_credentials("id", "secret", "invalid_env")

    def test_credential_roundtrip(self, db):
        """Secret stored in adapter_state is retrievable."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        with patch("circuitai.services.plaid_service.update_config"):
            svc.save_credentials("cid", "my_secret_123", "sandbox")

        row = db.fetchone(
            "SELECT value FROM adapter_state WHERE adapter_name = 'plaid' AND key = 'client_secret'"
        )
        assert row["value"] == "my_secret_123"


class TestAmountConversion:
    """Plaid amounts: positive = money leaving (debit). CircuitAI: negative = debit."""

    def test_debit_sign_flip(self, db):
        """Plaid $50 debit (positive) → CircuitAI -5000 cents."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)

        # Create an account and mapping
        db.execute(
            "INSERT INTO accounts (id, name, institution, account_type, balance_cents) VALUES (?, ?, ?, ?, ?)",
            ("acct-1", "Checking", "Chase", "checking", 0),
        )
        db.execute(
            "INSERT INTO plaid_account_map (id, plaid_account_id, entity_type, entity_id, institution) VALUES (?, ?, ?, ?, ?)",
            ("map-1", "plaid-acct-1", "account", "acct-1", "Chase"),
        )
        db.commit()

        txn = {
            "transaction_id": "txn-001",
            "account_id": "plaid-acct-1",
            "name": "Coffee Shop",
            "amount": 50.0,  # Plaid: positive = debit
            "date": "2026-01-15",
            "category": ["Food"],
        }
        svc._upsert_transaction(txn, "Chase")

        row = db.fetchone("SELECT amount_cents FROM account_transactions WHERE plaid_txn_id = 'txn-001'")
        assert row["amount_cents"] == -5000

    def test_credit_sign_flip(self, db):
        """Plaid -$1000 credit (negative) → CircuitAI +100000 cents."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)

        db.execute(
            "INSERT INTO accounts (id, name, institution, account_type, balance_cents) VALUES (?, ?, ?, ?, ?)",
            ("acct-2", "Checking", "BoA", "checking", 0),
        )
        db.execute(
            "INSERT INTO plaid_account_map (id, plaid_account_id, entity_type, entity_id, institution) VALUES (?, ?, ?, ?, ?)",
            ("map-2", "plaid-acct-2", "account", "acct-2", "BoA"),
        )
        db.commit()

        txn = {
            "transaction_id": "txn-002",
            "account_id": "plaid-acct-2",
            "name": "Payroll Deposit",
            "amount": -1000.0,  # Plaid: negative = credit
            "date": "2026-01-15",
            "category": ["Transfer"],
        }
        svc._upsert_transaction(txn, "BoA")

        row = db.fetchone("SELECT amount_cents FROM account_transactions WHERE plaid_txn_id = 'txn-002'")
        assert row["amount_cents"] == 100000


class TestDeduplication:
    def test_same_plaid_txn_id_only_one_row(self, db):
        """Inserting the same plaid_txn_id twice should update, not duplicate."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)

        db.execute(
            "INSERT INTO accounts (id, name, institution, account_type, balance_cents) VALUES (?, ?, ?, ?, ?)",
            ("acct-d", "Dedup Test", "Chase", "checking", 0),
        )
        db.execute(
            "INSERT INTO plaid_account_map (id, plaid_account_id, entity_type, entity_id, institution) VALUES (?, ?, ?, ?, ?)",
            ("map-d", "plaid-acct-d", "account", "acct-d", "Chase"),
        )
        db.commit()

        txn = {
            "transaction_id": "txn-dup",
            "account_id": "plaid-acct-d",
            "name": "Store Purchase",
            "amount": 25.0,
            "date": "2026-01-10",
            "category": ["Shopping"],
        }
        svc._upsert_transaction(txn, "Chase")
        # Insert again with updated description
        txn["name"] = "Store Purchase (Updated)"
        svc._upsert_transaction(txn, "Chase")

        rows = db.fetchall("SELECT * FROM account_transactions WHERE plaid_txn_id = 'txn-dup'")
        assert len(rows) == 1
        assert rows[0]["description"] == "Store Purchase (Updated)"


class TestAccountMapping:
    def test_depository_creates_account(self, db):
        """A depository/checking Plaid account creates an Account."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        svc._map_or_create_account(
            {"id": "plaid-chk", "name": "My Checking", "mask": "1234", "type": "depository", "subtype": "checking"},
            "Chase",
        )

        mapping = db.fetchone("SELECT * FROM plaid_account_map WHERE plaid_account_id = 'plaid-chk'")
        assert mapping["entity_type"] == "account"

        acct = db.fetchone(f"SELECT * FROM accounts WHERE id = '{mapping['entity_id']}'")
        assert acct["name"] == "My Checking"
        assert acct["institution"] == "Chase"
        assert acct["last_four"] == "1234"

    def test_credit_creates_card(self, db):
        """A credit/credit_card Plaid account creates a Card."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        svc._map_or_create_account(
            {"id": "plaid-cc", "name": "Sapphire", "mask": "5678", "type": "credit", "subtype": "credit card"},
            "Chase",
        )

        mapping = db.fetchone("SELECT * FROM plaid_account_map WHERE plaid_account_id = 'plaid-cc'")
        assert mapping["entity_type"] == "card"

        card = db.fetchone(f"SELECT * FROM cards WHERE id = '{mapping['entity_id']}'")
        assert card["name"] == "Sapphire"
        assert card["last_four"] == "5678"

    def test_idempotent_mapping(self, db):
        """Mapping the same plaid account twice doesn't create a duplicate."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        svc._map_or_create_account(
            {"id": "plaid-idem", "name": "Test", "mask": "", "type": "depository", "subtype": "checking"},
            "BoA",
        )
        svc._map_or_create_account(
            {"id": "plaid-idem", "name": "Test Changed", "mask": "", "type": "depository", "subtype": "checking"},
            "BoA",
        )

        count = db.fetchone("SELECT COUNT(*) as cnt FROM plaid_account_map WHERE plaid_account_id = 'plaid-idem'")
        assert count["cnt"] == 1

    def test_card_transactions_routed_correctly(self, db):
        """Transactions on credit accounts go to card_transactions."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        svc._map_or_create_account(
            {"id": "plaid-cc2", "name": "Visa", "mask": "9999", "type": "credit", "subtype": "credit card"},
            "Citi",
        )

        txn = {
            "transaction_id": "txn-card-1",
            "account_id": "plaid-cc2",
            "name": "Restaurant",
            "amount": 75.0,
            "date": "2026-02-01",
            "category": ["Food"],
        }
        svc._upsert_transaction(txn, "Citi")

        row = db.fetchone("SELECT * FROM card_transactions WHERE plaid_txn_id = 'txn-card-1'")
        assert row is not None
        assert row["amount_cents"] == -7500

        # Confirm it did NOT go to account_transactions
        acct_row = db.fetchone("SELECT * FROM account_transactions WHERE plaid_txn_id = 'txn-card-1'")
        assert acct_row is None


class TestRecurringDetection:
    def test_creates_bill_from_stream(self, db):
        """An active outflow stream creates a bill with correct amount and due_day."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)

        mock_client = MagicMock()
        mock_client.transactions_recurring_get.return_value = {
            "outflow_streams": [
                {
                    "stream_id": "stream-001",
                    "is_active": True,
                    "merchant_name": "Netflix",
                    "description": "NETFLIX.COM",
                    "last_amount": {"amount": 15.99},
                    "frequency": "MONTHLY",
                    "last_date": "2026-01-15",
                    "category": ["Entertainment"],
                }
            ],
            "inflow_streams": [],
        }
        svc._client = mock_client

        created = svc._sync_recurring("fake_access_token")
        assert created == 1

        bill = db.fetchone("SELECT * FROM bills WHERE name = 'Netflix'")
        assert bill is not None
        assert bill["amount_cents"] == 1599
        assert bill["due_day"] == 15
        assert bill["frequency"] == "monthly"

    def test_no_duplicate_on_resync(self, db):
        """Re-syncing the same stream doesn't create a second bill."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)

        mock_client = MagicMock()
        mock_client.transactions_recurring_get.return_value = {
            "outflow_streams": [
                {
                    "stream_id": "stream-002",
                    "is_active": True,
                    "merchant_name": "Spotify",
                    "description": "SPOTIFY",
                    "last_amount": {"amount": 9.99},
                    "frequency": "MONTHLY",
                    "last_date": "2026-02-01",
                    "category": ["Entertainment"],
                }
            ],
            "inflow_streams": [],
        }
        svc._client = mock_client

        svc._sync_recurring("fake_token")
        svc._sync_recurring("fake_token")

        rows = db.fetchall("SELECT * FROM bills WHERE name = 'Spotify'")
        assert len(rows) == 1


class TestSyncAll:
    def test_sync_all_no_items_raises(self, db):
        """sync_all raises when no items are connected."""
        from circuitai.core.exceptions import AdapterError
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)
        with pytest.raises(AdapterError, match="No connected bank"):
            svc.sync_all()


class TestRemoveTransaction:
    def test_remove_by_plaid_txn_id(self, db):
        """Removing a transaction by plaid_txn_id deletes it."""
        from circuitai.services.plaid_service import PlaidService

        svc = PlaidService(db)

        db.execute(
            "INSERT INTO accounts (id, name, institution, account_type, balance_cents) VALUES (?, ?, ?, ?, ?)",
            ("acct-rm", "Remove Test", "Chase", "checking", 0),
        )
        db.execute(
            "INSERT INTO plaid_account_map (id, plaid_account_id, entity_type, entity_id, institution) VALUES (?, ?, ?, ?, ?)",
            ("map-rm", "plaid-rm", "account", "acct-rm", "Chase"),
        )
        db.commit()

        txn = {
            "transaction_id": "txn-remove",
            "account_id": "plaid-rm",
            "name": "To be removed",
            "amount": 10.0,
            "date": "2026-01-01",
            "category": [],
        }
        svc._upsert_transaction(txn, "Chase")
        assert db.fetchone("SELECT id FROM account_transactions WHERE plaid_txn_id = 'txn-remove'") is not None

        svc._remove_transaction("txn-remove")
        assert db.fetchone("SELECT id FROM account_transactions WHERE plaid_txn_id = 'txn-remove'") is None


# ── PlaidAdapter tests ───────────────────────────────────────────


class TestPlaidAdapter:
    def test_metadata(self):
        from circuitai.adapters.builtin.plaid_adapter import PlaidAdapter

        adapter = PlaidAdapter()
        meta = adapter.metadata()
        assert meta["name"] == "plaid"
        assert "version" in meta
        assert "description" in meta

    def test_configure_raises(self):
        from circuitai.adapters.builtin.plaid_adapter import PlaidAdapter
        from circuitai.core.exceptions import AdapterError

        adapter = PlaidAdapter()
        with pytest.raises(AdapterError, match="browser-based"):
            adapter.configure()

    def test_validate_config(self):
        from circuitai.adapters.builtin.plaid_adapter import PlaidAdapter

        adapter = PlaidAdapter()
        # Returns True if plaid-python is importable (it may or may not be installed)
        result = adapter.validate_config()
        assert isinstance(result, bool)


# ── Link Server tests ────────────────────────────────────────────


class TestLinkServer:
    def test_cancelled_flow_raises(self):
        """If user cancels Plaid Link, run_link_flow raises AdapterError."""
        from circuitai.core.exceptions import AdapterError
        from circuitai.services.plaid_link_server import run_link_flow

        # Mock the HTTPServer to immediately return a cancelled result
        with patch("circuitai.services.plaid_link_server.HTTPServer") as MockServer, \
             patch("circuitai.services.plaid_link_server.webbrowser"):
            server_instance = MagicMock()

            def fake_serve_forever():
                # Simulate the handler setting cancelled
                pass

            server_instance.serve_forever = fake_serve_forever
            MockServer.return_value = server_instance

            # We need to simulate what happens: the server starts, the callback
            # sets result["cancelled"] = True, then serve_forever returns.
            # Since we mock serve_forever to be a no-op, result stays empty,
            # which triggers "No public token received"
            with pytest.raises(AdapterError, match="No public token"):
                run_link_flow("fake-link-token", port=0)


# ── Migration tests ──────────────────────────────────────────────


class TestPlaidMigration:
    def test_v2_migration_creates_tables_and_columns(self, db):
        """The v2 migration creates plaid_account_map and adds plaid_txn_id columns."""
        # Verify plaid_account_map exists
        row = db.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name='plaid_account_map'")
        assert row is not None

        # Verify plaid_txn_id columns exist
        acct_cols = [r["name"] for r in db.execute("PRAGMA table_info(account_transactions)").fetchall()]
        assert "plaid_txn_id" in acct_cols

        card_cols = [r["name"] for r in db.execute("PRAGMA table_info(card_transactions)").fetchall()]
        assert "plaid_txn_id" in card_cols

    def test_schema_version_is_current(self, db):
        from circuitai.core.migrations import CURRENT_SCHEMA_VERSION
        row = db.fetchone("SELECT MAX(version) as v FROM schema_version")
        assert row["v"] == CURRENT_SCHEMA_VERSION
