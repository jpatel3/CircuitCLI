"""Tests for bill service."""

import tempfile
from pathlib import Path

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.services.bill_service import BillService


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


@pytest.fixture
def svc(db):
    return BillService(db)


class TestBillService:
    def test_add_bill(self, svc):
        bill = svc.add_bill(name="JCPL Electric", provider="JCPL", category="electricity", amount_cents=14200, due_day=15)
        assert bill.name == "JCPL Electric"
        assert bill.amount_cents == 14200
        assert bill.due_day == 15

    def test_list_bills(self, svc):
        svc.add_bill(name="Bill1", amount_cents=100)
        svc.add_bill(name="Bill2", amount_cents=200)
        bills = svc.list_bills()
        assert len(bills) == 2

    def test_get_bill(self, svc):
        bill = svc.add_bill(name="Test", amount_cents=1000)
        fetched = svc.get_bill(bill.id)
        assert fetched.name == "Test"

    def test_update_bill(self, svc):
        bill = svc.add_bill(name="Old Name", amount_cents=100)
        updated = svc.update_bill(bill.id, name="New Name", amount_cents=200)
        assert updated.name == "New Name"
        assert updated.amount_cents == 200

    def test_delete_bill(self, svc):
        bill = svc.add_bill(name="To Delete", amount_cents=100)
        svc.delete_bill(bill.id)
        # Should not show in active list
        bills = svc.list_bills()
        assert len(bills) == 0

    def test_pay_bill(self, svc):
        bill = svc.add_bill(name="Electric", amount_cents=15000, due_day=15)
        payment = svc.pay_bill(bill.id, amount_cents=15000, paid_date="2026-02-15")
        assert payment.amount_cents == 15000
        assert payment.bill_id == bill.id

    def test_pay_bill_default_amount(self, svc):
        bill = svc.add_bill(name="Water", amount_cents=6750)
        payment = svc.pay_bill(bill.id)
        assert payment.amount_cents == 6750

    def test_get_payments(self, svc):
        bill = svc.add_bill(name="Gas", amount_cents=8000)
        svc.pay_bill(bill.id, paid_date="2026-01-15")
        svc.pay_bill(bill.id, paid_date="2026-02-15")
        payments = svc.get_payments(bill.id)
        assert len(payments) == 2

    def test_search_bills(self, svc):
        svc.add_bill(name="JCPL Electric", provider="JCPL")
        svc.add_bill(name="American Water", provider="American Water")
        results = svc.search_bills("jcpl")
        assert len(results) == 1
        assert results[0].name == "JCPL Electric"

    def test_get_summary(self, svc):
        svc.add_bill(name="Monthly Bill", amount_cents=10000, frequency="monthly")
        svc.add_bill(name="Yearly Bill", amount_cents=120000, frequency="yearly")
        summary = svc.get_summary()
        assert summary["total_bills"] == 2
        assert summary["monthly_total_cents"] == 10000
        assert summary["yearly_total_cents"] == 120000
        assert summary["estimated_monthly_cents"] == 10000 + 10000  # monthly + yearly/12

    def test_validation_no_name(self, svc):
        from circuitai.core.exceptions import ValidationError
        with pytest.raises(ValidationError, match="name"):
            svc.add_bill(name="", amount_cents=100)

    def test_validation_negative_amount(self, svc):
        from circuitai.core.exceptions import ValidationError
        with pytest.raises(ValidationError, match="negative"):
            svc.add_bill(name="Bad", amount_cents=-100)


class TestBillDeadlineIntegration:
    """Tests for auto-creating deadlines from bills (#29)."""

    def test_add_bill_creates_deadline(self, db):
        from circuitai.services.deadline_service import DeadlineService
        svc = BillService(db)
        dl_svc = DeadlineService(db)

        bill = svc.add_bill(name="JCPL Electric", amount_cents=14200, due_day=15)
        deadlines = dl_svc.list_deadlines()
        linked = [d for d in deadlines if d.linked_bill_id == bill.id]
        assert len(linked) == 1
        assert "JCPL Electric" in linked[0].title
        assert linked[0].priority == "high"
        assert linked[0].category == "bill"

    def test_add_bill_no_due_day_no_deadline(self, db):
        from circuitai.services.deadline_service import DeadlineService
        svc = BillService(db)
        dl_svc = DeadlineService(db)

        svc.add_bill(name="No Due Day Bill", amount_cents=5000)
        deadlines = dl_svc.list_deadlines()
        assert len(deadlines) == 0

    def test_no_duplicate_deadlines(self, db):
        from circuitai.models.deadline import DeadlineRepository
        svc = BillService(db)

        bill = svc.add_bill(name="Water", amount_cents=6750, due_day=20)
        # Manually call _ensure_deadline again
        svc._ensure_deadline(bill)
        svc._ensure_deadline(bill)

        dl_repo = DeadlineRepository(db)
        linked = dl_repo.find_by_linked_bill(bill.id)
        assert len(linked) == 1

    def test_pay_bill_completes_deadline_and_creates_next(self, db):
        from circuitai.services.deadline_service import DeadlineService
        from circuitai.models.deadline import DeadlineRepository
        svc = BillService(db)
        dl_svc = DeadlineService(db)
        dl_repo = DeadlineRepository(db)

        bill = svc.add_bill(name="Gas", amount_cents=8000, due_day=10, frequency="monthly")
        # Should have 1 active deadline
        linked = dl_repo.find_by_linked_bill(bill.id, active_only=True)
        assert len(linked) == 1

        # Pay the bill
        svc.pay_bill(bill.id, amount_cents=8000, paid_date="2026-02-10")

        # Old deadline should be completed
        all_linked = dl_repo.find_by_linked_bill(bill.id, active_only=False)
        completed = [d for d in all_linked if d.is_completed]
        assert len(completed) == 1

        # New deadline should exist for next cycle
        active = dl_repo.find_by_linked_bill(bill.id, active_only=True)
        assert len(active) == 1
        assert active[0].due_date > completed[0].due_date

    def test_pay_onetime_bill_no_renewal(self, db):
        from circuitai.models.deadline import DeadlineRepository
        svc = BillService(db)
        dl_repo = DeadlineRepository(db)

        bill = svc.add_bill(name="One-Time Fee", amount_cents=50000, due_day=15, frequency="one-time")
        assert len(dl_repo.find_by_linked_bill(bill.id, active_only=True)) == 1

        svc.pay_bill(bill.id, amount_cents=50000, paid_date="2026-02-15")

        # Should have no active deadline (completed, no renewal)
        active = dl_repo.find_by_linked_bill(bill.id, active_only=True)
        assert len(active) == 0
