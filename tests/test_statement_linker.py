"""Tests for statement linking service."""

import tempfile
from pathlib import Path

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.models.base import new_id, now_iso
from circuitai.services.bill_service import BillService
from circuitai.services.statement_linker import StatementLinker


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


def _add_transaction(db, account_id, description, amount_cents, txn_date):
    """Helper to insert a transaction."""
    tid = new_id()
    db.execute(
        """INSERT INTO account_transactions
           (id, account_id, description, amount_cents, transaction_date, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (tid, account_id, description, amount_cents, txn_date, now_iso()),
    )
    db.commit()
    return tid


def _add_account(db, name="Test Account"):
    """Helper to insert a bank account."""
    from circuitai.services.account_service import AccountService

    svc = AccountService(db)
    return svc.add_account(name=name, institution="Test Bank")


class TestStatementLinker:
    def test_match_by_description_pattern(self, db):
        bill_svc = BillService(db)
        bill = bill_svc.add_bill(
            name="JCPL Electric", provider="JCPL",
            amount_cents=14200, due_day=15,
        )

        acct = _add_account(db)
        _add_transaction(db, acct.id, "JCPL PAYMENT ELECTRIC", -14200, "2026-02-15")

        linker = StatementLinker(db)
        result = linker.link_transactions()

        assert result["matched"] == 1
        assert result["matches"][0]["bill_id"] == bill.id

    def test_no_match_when_pattern_missing(self, db):
        BillService(db).add_bill(name="Water Bill", amount_cents=6750, due_day=20)

        acct = _add_account(db)
        _add_transaction(db, acct.id, "RANDOM MERCHANT", -5000, "2026-02-15")

        linker = StatementLinker(db)
        result = linker.link_transactions()
        assert result["matched"] == 0

    def test_amount_tolerance(self, db):
        bill_svc = BillService(db)
        bill_svc.add_bill(
            name="Gas Bill", provider="ELIZGAS",
            amount_cents=9500, due_day=12,
        )

        acct = _add_account(db)
        # Amount within $5 tolerance (9500 vs 9700 = $2 diff)
        _add_transaction(db, acct.id, "ELIZGAS PAYMENT", -9700, "2026-02-12")

        linker = StatementLinker(db, amount_tolerance_cents=500)
        result = linker.link_transactions()
        assert result["matched"] == 1

    def test_amount_outside_tolerance(self, db):
        bill_svc = BillService(db)
        bill_svc.add_bill(
            name="Gas Bill", provider="ELIZGAS",
            amount_cents=9500, due_day=12,
        )

        acct = _add_account(db)
        # Amount way off (9500 vs 50000)
        _add_transaction(db, acct.id, "ELIZGAS PAYMENT", -50000, "2026-02-12")

        linker = StatementLinker(db, amount_tolerance_cents=500)
        result = linker.link_transactions()
        # Still matches by description pattern alone (score >= 0.4 from 0.5 desc match)
        assert result["matched"] == 1

    def test_date_proximity_scoring(self, db):
        bill_svc = BillService(db)
        bill_svc.add_bill(
            name="Internet", provider="XFINITY",
            amount_cents=8999, due_day=5,
        )

        acct = _add_account(db)
        # Exact date match
        _add_transaction(db, acct.id, "XFINITY INTERNET", -8999, "2026-02-05")

        linker = StatementLinker(db)
        result = linker.link_transactions()
        assert result["matched"] == 1
        # Score should be high (description + amount + date all match)
        assert result["matches"][0]["score"] >= 0.9

    def test_learn_pattern(self, db):
        bill_svc = BillService(db)
        bill = bill_svc.add_bill(name="Electric", amount_cents=14200, due_day=15)

        linker = StatementLinker(db)
        linker.learn_pattern(bill.id, "JCPL ELECTRIC PAYMENT ACH")

        # Check the pattern was added
        refreshed = bill_svc.get_bill(bill.id)
        # "PAYMENT" and "ACH" are skipped as common words, leaving "JCPL ELECTRIC"
        assert "JCPL ELECTRIC" in refreshed.patterns

    def test_confirm_match(self, db):
        bill_svc = BillService(db)
        bill = bill_svc.add_bill(name="Water", amount_cents=6750, due_day=20)

        acct = _add_account(db)
        tid = _add_transaction(db, acct.id, "AMERICAN WATER CO PAYMENT", -6750, "2026-02-20")

        linker = StatementLinker(db)
        linker.confirm_match(tid, bill.id)

        # Transaction should be marked as matched
        row = db.fetchone(
            "SELECT is_matched, linked_bill_id FROM account_transactions WHERE id = ?",
            (tid,),
        )
        assert row["is_matched"] == 1
        assert row["linked_bill_id"] == bill.id

        # Pattern should be learned
        refreshed = bill_svc.get_bill(bill.id)
        assert len(refreshed.patterns) > 0

    def test_get_unmatched(self, db):
        acct = _add_account(db)
        _add_transaction(db, acct.id, "MERCHANT A", -1000, "2026-02-01")
        _add_transaction(db, acct.id, "MERCHANT B", -2000, "2026-02-02")

        linker = StatementLinker(db)
        unmatched = linker.get_unmatched()
        assert len(unmatched) == 2

    def test_already_matched_not_relinked(self, db):
        bill_svc = BillService(db)
        bill_svc.add_bill(
            name="Electric", provider="JCPL",
            amount_cents=14200, due_day=15,
        )

        acct = _add_account(db)
        _add_transaction(db, acct.id, "JCPL PAYMENT", -14200, "2026-02-15")

        linker = StatementLinker(db)
        result1 = linker.link_transactions()
        assert result1["matched"] == 1

        # Run again — should not re-match
        result2 = linker.link_transactions()
        assert result2["matched"] == 0
        assert result2["total_unmatched"] == 0
