"""Tests for screen capture service — fingerprints, extraction, import, dedup, migration."""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import get_schema_version, initialize_database
from circuitai.services.capture_service import CaptureService, compute_txn_fingerprint


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test_capture.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


def _seed_account(db) -> str:
    """Create a test account and return its ID."""
    from circuitai.models.base import new_id, now_iso

    aid = new_id()
    db.execute(
        """INSERT INTO accounts (id, name, institution, account_type, balance_cents, is_active, created_at, updated_at)
           VALUES (?, 'Test Checking', 'TestBank', 'checking', 100000, 1, ?, ?)""",
        (aid, now_iso(), now_iso()),
    )
    db.commit()
    return aid


def _seed_card(db) -> str:
    """Create a test card and return its ID."""
    from circuitai.models.base import new_id, now_iso

    cid = new_id()
    db.execute(
        """INSERT INTO cards (id, name, institution, last_four, credit_limit_cents, balance_cents, is_active, created_at, updated_at)
           VALUES (?, 'Test Visa', 'TestBank', '4321', 500000, 25000, 1, ?, ?)""",
        (cid, now_iso(), now_iso()),
    )
    db.commit()
    return cid


# ── Migration tests ──────────────────────────────────────────────


class TestMigrationV3:
    def test_schema_version_is_3(self, db):
        assert get_schema_version(db) == 3

    def test_account_transactions_has_fingerprint(self, db):
        cols = [row["name"] for row in db.fetchall("PRAGMA table_info(account_transactions)")]
        assert "txn_fingerprint" in cols

    def test_card_transactions_has_fingerprint(self, db):
        cols = [row["name"] for row in db.fetchall("PRAGMA table_info(card_transactions)")]
        assert "txn_fingerprint" in cols

    def test_fingerprint_unique_index_works(self, db):
        """Inserting duplicate fingerprints into account_transactions should raise."""
        from circuitai.models.base import new_id, now_iso

        aid = _seed_account(db)
        db.execute(
            """INSERT INTO account_transactions (id, account_id, description, amount_cents, transaction_date, txn_fingerprint, created_at)
               VALUES (?, ?, 'Test', -1000, '2025-01-15', 'fp_unique_test', ?)""",
            (new_id(), aid, now_iso()),
        )
        db.commit()

        with pytest.raises(Exception):  # IntegrityError
            db.execute(
                """INSERT INTO account_transactions (id, account_id, description, amount_cents, transaction_date, txn_fingerprint, created_at)
                   VALUES (?, ?, 'Test2', -2000, '2025-01-16', 'fp_unique_test', ?)""",
                (new_id(), aid, now_iso()),
            )

    def test_null_fingerprints_allowed_multiple(self, db):
        """Multiple NULL fingerprints should be allowed (old rows)."""
        from circuitai.models.base import new_id, now_iso

        aid = _seed_account(db)
        for i in range(3):
            db.execute(
                """INSERT INTO account_transactions (id, account_id, description, amount_cents, transaction_date, created_at)
                   VALUES (?, ?, ?, ?, '2025-01-15', ?)""",
                (new_id(), aid, f"Null fp txn {i}", -100 * i, now_iso()),
            )
        db.commit()
        count = db.fetchone("SELECT COUNT(*) as c FROM account_transactions WHERE txn_fingerprint IS NULL")
        assert count["c"] == 3


# ── Fingerprint tests ────────────────────────────────────────────


class TestFingerprint:
    def test_deterministic(self):
        fp1 = compute_txn_fingerprint("2025-01-15", "AMAZON.COM", -4299)
        fp2 = compute_txn_fingerprint("2025-01-15", "AMAZON.COM", -4299)
        assert fp1 == fp2

    def test_normalizes_case(self):
        fp1 = compute_txn_fingerprint("2025-01-15", "Amazon.com", -4299)
        fp2 = compute_txn_fingerprint("2025-01-15", "AMAZON.COM", -4299)
        assert fp1 == fp2

    def test_normalizes_punctuation(self):
        fp1 = compute_txn_fingerprint("2025-01-15", "AMAZON.COM*1234", -4299)
        fp2 = compute_txn_fingerprint("2025-01-15", "AMAZONCOM1234", -4299)
        assert fp1 == fp2

    def test_different_amounts_differ(self):
        fp1 = compute_txn_fingerprint("2025-01-15", "AMAZON", -4299)
        fp2 = compute_txn_fingerprint("2025-01-15", "AMAZON", -5000)
        assert fp1 != fp2

    def test_different_dates_differ(self):
        fp1 = compute_txn_fingerprint("2025-01-15", "AMAZON", -4299)
        fp2 = compute_txn_fingerprint("2025-01-16", "AMAZON", -4299)
        assert fp1 != fp2

    def test_length_is_16(self):
        fp = compute_txn_fingerprint("2025-01-15", "Test", -100)
        assert len(fp) == 16

    def test_hex_characters_only(self):
        fp = compute_txn_fingerprint("2025-01-15", "Test", -100)
        assert all(c in "0123456789abcdef" for c in fp)


# ── Credentials tests ────────────────────────────────────────────


class TestCaptureCredentials:
    def test_save_and_read_roundtrip(self, db):
        svc = CaptureService(db)
        assert not svc.is_configured()

        svc.save_api_key("sk-ant-test-key-123")
        assert svc.is_configured()

        key = svc._get_api_key()
        assert key == "sk-ant-test-key-123"

    def test_update_key(self, db):
        svc = CaptureService(db)
        svc.save_api_key("old-key")
        svc.save_api_key("new-key")
        assert svc._get_api_key() == "new-key"

    def test_is_configured_false_when_empty(self, db):
        svc = CaptureService(db)
        assert not svc.is_configured()


# ── Screenshot tests ─────────────────────────────────────────────


class TestScreenshot:
    def test_non_macos_raises(self, db):
        svc = CaptureService(db)
        with patch("circuitai.services.capture_service.sys") as mock_sys:
            mock_sys.platform = "linux"
            from circuitai.core.exceptions import AdapterError
            with pytest.raises(AdapterError, match="only supported on macOS"):
                svc.take_screenshot()

    def test_cancelled_raises(self, db):
        svc = CaptureService(db)
        with patch("circuitai.services.capture_service.sys") as mock_sys:
            mock_sys.platform = "darwin"
            with patch("circuitai.services.capture_service.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=1)
                from circuitai.core.exceptions import AdapterError
                with pytest.raises(AdapterError, match="cancelled or failed"):
                    svc.take_screenshot()


# ── Vision extraction tests ──────────────────────────────────────


class TestVisionExtraction:
    def _make_svc(self, db):
        svc = CaptureService(db)
        svc.save_api_key("test-key")
        return svc

    def test_valid_json_parse(self, db):
        svc = self._make_svc(db)
        response_json = json.dumps({
            "account_name": "Chase Checking",
            "account_type": "checking",
            "balance_cents": 150000,
            "transactions": [
                {"date": "2025-01-15", "description": "AMAZON", "amount_cents": -4299, "category": "shopping"},
            ],
        })

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=response_json)]

        with patch("circuitai.services.capture_service.HAS_ANTHROPIC", True):
            with patch("circuitai.services.capture_service.anthropic", create=True) as mock_anthropic:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = mock_message
                mock_anthropic.Anthropic.return_value = mock_client

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
                    tmp_path = Path(f.name)

                try:
                    result = svc.extract_from_screenshot(tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)

                assert result["account_name"] == "Chase Checking"
                assert result["balance_cents"] == 150000
                assert len(result["transactions"]) == 1
                assert result["transactions"][0]["amount_cents"] == -4299

    def test_handles_json_wrapping(self, db):
        svc = self._make_svc(db)
        wrapped = '```json\n{"account_name": "Test", "account_type": "checking", "balance_cents": null, "transactions": []}\n```'

        mock_message = MagicMock()
        mock_message.content = [MagicMock(text=wrapped)]

        with patch("circuitai.services.capture_service.HAS_ANTHROPIC", True):
            with patch("circuitai.services.capture_service.anthropic", create=True) as mock_anthropic:
                mock_client = MagicMock()
                mock_client.messages.create.return_value = mock_message
                mock_anthropic.Anthropic.return_value = mock_client

                with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                    f.write(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)
                    tmp_path = Path(f.name)

                try:
                    result = svc.extract_from_screenshot(tmp_path)
                finally:
                    tmp_path.unlink(missing_ok=True)

                assert result["account_name"] == "Test"
                assert result["transactions"] == []

    def test_no_anthropic_package_raises(self, db):
        svc = self._make_svc(db)
        with patch("circuitai.services.capture_service.HAS_ANTHROPIC", False):
            from circuitai.core.exceptions import AdapterError
            with pytest.raises(AdapterError, match="anthropic package not installed"):
                svc.extract_from_screenshot(Path("/tmp/fake.png"))


# ── Import + dedup tests ─────────────────────────────────────────


class TestImportAndDedup:
    def test_new_transactions_import(self, db):
        aid = _seed_account(db)
        svc = CaptureService(db)

        data = {
            "balance_cents": 95000,
            "transactions": [
                {"date": "2025-01-15", "description": "GROCERY STORE", "amount_cents": -5000, "category": "food"},
                {"date": "2025-01-16", "description": "GAS STATION", "amount_cents": -3500, "category": "transport"},
            ],
        }

        result = svc.import_transactions(data, aid, "account")
        assert result["imported"] == 2
        assert result["skipped"] == 0
        assert result["balance_updated"] is True

        rows = db.fetchall("SELECT * FROM account_transactions WHERE account_id = ?", (aid,))
        assert len(rows) == 2

        # Verify balance updated
        acct = db.fetchone("SELECT balance_cents FROM accounts WHERE id = ?", (aid,))
        assert acct["balance_cents"] == 95000

    def test_same_data_twice_skips(self, db):
        aid = _seed_account(db)
        svc = CaptureService(db)

        data = {
            "transactions": [
                {"date": "2025-01-15", "description": "COFFEE SHOP", "amount_cents": -450, "category": "food"},
            ],
        }

        r1 = svc.import_transactions(data, aid, "account")
        assert r1["imported"] == 1
        assert r1["skipped"] == 0

        r2 = svc.import_transactions(data, aid, "account")
        assert r2["imported"] == 0
        assert r2["skipped"] == 1

        rows = db.fetchall("SELECT * FROM account_transactions WHERE account_id = ?", (aid,))
        assert len(rows) == 1

    def test_cross_source_dedup_csv_blocks_capture(self, db):
        """A CSV-imported fingerprint should block the same transaction from capture."""
        aid = _seed_account(db)
        from circuitai.models.base import new_id, now_iso

        # Simulate CSV import with fingerprint
        fp = compute_txn_fingerprint("2025-02-01", "ELECTRIC COMPANY", -15000)
        db.execute(
            """INSERT INTO account_transactions
               (id, account_id, description, amount_cents, transaction_date, txn_fingerprint, created_at)
               VALUES (?, ?, 'ELECTRIC COMPANY', -15000, '2025-02-01', ?, ?)""",
            (new_id(), aid, fp, now_iso()),
        )
        db.commit()

        # Now try capture import with the same transaction
        svc = CaptureService(db)
        data = {
            "transactions": [
                {"date": "2025-02-01", "description": "ELECTRIC COMPANY", "amount_cents": -15000, "category": ""},
            ],
        }
        result = svc.import_transactions(data, aid, "account")
        assert result["imported"] == 0
        assert result["skipped"] == 1

    def test_card_transactions_routed_correctly(self, db):
        cid = _seed_card(db)
        svc = CaptureService(db)

        data = {
            "balance_cents": 30000,
            "transactions": [
                {"date": "2025-01-20", "description": "RESTAURANT", "amount_cents": -5000, "category": "dining"},
            ],
        }

        result = svc.import_transactions(data, cid, "card")
        assert result["imported"] == 1

        rows = db.fetchall("SELECT * FROM card_transactions WHERE card_id = ?", (cid,))
        assert len(rows) == 1
        assert rows[0]["description"] == "RESTAURANT"
        assert rows[0]["txn_fingerprint"] is not None

        # Verify card balance updated
        card = db.fetchone("SELECT balance_cents FROM cards WHERE id = ?", (cid,))
        assert card["balance_cents"] == 30000

    def test_cross_table_dedup(self, db):
        """A fingerprint in card_transactions should block import into account_transactions."""
        aid = _seed_account(db)
        cid = _seed_card(db)
        svc = CaptureService(db)

        # Import to card first
        data = {
            "transactions": [
                {"date": "2025-03-01", "description": "STREAMING SERVICE", "amount_cents": -1599, "category": ""},
            ],
        }
        r1 = svc.import_transactions(data, cid, "card")
        assert r1["imported"] == 1

        # Try importing same to account — should be deduped
        r2 = svc.import_transactions(data, aid, "account")
        assert r2["imported"] == 0
        assert r2["skipped"] == 1

    def test_missing_date_skipped(self, db):
        aid = _seed_account(db)
        svc = CaptureService(db)

        data = {
            "transactions": [
                {"date": "", "description": "NO DATE TXN", "amount_cents": -100, "category": ""},
            ],
        }

        result = svc.import_transactions(data, aid, "account")
        assert result["imported"] == 0
        assert len(result["errors"]) == 1

    def test_empty_transactions_list(self, db):
        aid = _seed_account(db)
        svc = CaptureService(db)

        data = {"transactions": [], "balance_cents": 50000}
        result = svc.import_transactions(data, aid, "account")
        assert result["imported"] == 0
        assert result["skipped"] == 0
        assert result["balance_updated"] is True


# ── Snap orchestration test ──────────────────────────────────────


class TestSnapOrchestration:
    def test_snap_full_flow(self, db):
        aid = _seed_account(db)
        svc = CaptureService(db)
        svc.save_api_key("test-key")

        extraction = {
            "account_name": "Chase",
            "balance_cents": 80000,
            "transactions": [
                {"date": "2025-01-20", "description": "GROCERY", "amount_cents": -2500, "category": "food"},
            ],
        }

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(b"\x89PNG" + b"\x00" * 100)
            tmp_path = Path(f.name)

        with patch.object(svc, "take_screenshot", return_value=tmp_path):
            with patch.object(svc, "extract_from_screenshot", return_value=extraction):
                with patch.object(svc, "run_statement_linking", return_value={"matched": 0}):
                    result = svc.snap(aid, "account")

        assert result["imported"] == 1
        assert result["linked"] == 0
        assert result["balance_updated"] is True
        # Temp file should be cleaned up
        assert not tmp_path.exists()
