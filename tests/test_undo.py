"""Tests for undo service."""

import tempfile
from pathlib import Path

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.services.undo_service import UndoAction, UndoService


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


class TestUndoService:
    def test_nothing_to_undo(self, db):
        svc = UndoService(db)
        assert not svc.has_undo
        assert svc.undo() == "Nothing to undo."

    def test_undo_add_bill(self, db):
        from circuitai.services.bill_service import BillService

        bill_svc = BillService(db)
        bill = bill_svc.add_bill(name="Test Bill", amount_cents=5000)

        svc = UndoService(db)
        svc.record(UndoAction(
            action_type="add",
            entity_type="bill",
            entity_id=bill.id,
            description="Added bill: Test Bill",
        ))

        assert svc.has_undo
        result = svc.undo()
        assert "Undone" in result

        # Bill should be gone
        bills = bill_svc.list_bills()
        assert len(bills) == 0
        assert not svc.has_undo

    def test_undo_pay_bill(self, db):
        from circuitai.services.bill_service import BillService

        bill_svc = BillService(db)
        bill = bill_svc.add_bill(name="Electric", amount_cents=15000)
        payment = bill_svc.pay_bill(bill.id, amount_cents=15000)

        svc = UndoService(db)
        svc.record(UndoAction(
            action_type="pay",
            entity_type="bill",
            entity_id=payment.id,
            description="Paid Electric: $150.00",
        ))

        result = svc.undo()
        assert "Undone" in result

        # Payment should be gone
        payments = bill_svc.get_payments(bill.id)
        assert len(payments) == 0

    def test_undo_complete_deadline(self, db):
        from circuitai.services.deadline_service import DeadlineService

        dl_svc = DeadlineService(db)
        dl = dl_svc.add_deadline(title="Test DL", due_date="2026-03-15")
        dl_svc.complete_deadline(dl.id)

        svc = UndoService(db)
        svc.record(UndoAction(
            action_type="complete",
            entity_type="deadline",
            entity_id=dl.id,
            description="Completed deadline: Test DL",
        ))

        result = svc.undo()
        assert "Undone" in result

        # Deadline should be incomplete again
        refreshed = dl_svc.get_deadline(dl.id)
        assert not refreshed.is_completed

    def test_undo_delete_bill(self, db):
        from circuitai.services.bill_service import BillService

        bill_svc = BillService(db)
        bill = bill_svc.add_bill(name="To Delete", amount_cents=1000)
        bill_svc.delete_bill(bill.id)

        # Should be gone from active list
        assert len(bill_svc.list_bills()) == 0

        svc = UndoService(db)
        svc.record(UndoAction(
            action_type="delete",
            entity_type="bill",
            entity_id=bill.id,
            description="Deleted bill: To Delete",
        ))

        result = svc.undo()
        assert "Undone" in result

        # Should be back
        assert len(bill_svc.list_bills()) == 1

    def test_single_level_undo(self, db):
        """Only the last action can be undone."""
        from circuitai.services.bill_service import BillService

        bill_svc = BillService(db)
        bill1 = bill_svc.add_bill(name="Bill 1", amount_cents=100)
        bill2 = bill_svc.add_bill(name="Bill 2", amount_cents=200)

        svc = UndoService(db)
        svc.record(UndoAction(
            action_type="add", entity_type="bill",
            entity_id=bill1.id, description="Added Bill 1",
        ))
        svc.record(UndoAction(
            action_type="add", entity_type="bill",
            entity_id=bill2.id, description="Added Bill 2",
        ))

        # Undo should only undo bill2
        svc.undo()
        bills = bill_svc.list_bills()
        assert len(bills) == 1
        assert bills[0].name == "Bill 1"

        # Second undo should say nothing
        assert svc.undo() == "Nothing to undo."
