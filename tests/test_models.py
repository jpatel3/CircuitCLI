"""Tests for Pydantic models and repositories."""

import tempfile
from pathlib import Path

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import NotFoundError
from circuitai.core.migrations import initialize_database
from circuitai.models.account import Account
from circuitai.models.activity import Child, ChildRepository
from circuitai.models.bill import Bill, BillRepository
from circuitai.models.card import Card
from circuitai.models.deadline import Deadline
from circuitai.models.investment import Investment


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


class TestBillModel:
    def test_bill_creation(self):
        bill = Bill(name="Electric", amount_cents=14200, due_day=15)
        assert bill.amount_dollars == 142.0
        assert bill.name == "Electric"

    def test_bill_patterns(self):
        bill = Bill(name="Electric", amount_cents=0)
        bill.add_pattern("JCPL")
        bill.add_pattern("JCP&L")
        assert bill.patterns == ["JCPL", "JCP&L"]
        # Duplicate
        bill.add_pattern("JCPL")
        assert len(bill.patterns) == 2


class TestAccountModel:
    def test_account_creation(self):
        acct = Account(name="Chase Checking", institution="Chase", balance_cents=520000)
        assert acct.balance_dollars == 5200.0


class TestCardModel:
    def test_utilization(self):
        card = Card(name="Amex", institution="Amex", balance_cents=120500, credit_limit_cents=1000000)
        assert card.utilization_pct == pytest.approx(12.05)


class TestInvestmentModel:
    def test_gain_loss(self):
        inv = Investment(
            name="Wealthfront", institution="Wealthfront",
            current_value_cents=110000, cost_basis_cents=100000,
        )
        assert inv.gain_loss_cents == 10000
        assert inv.gain_loss_pct == pytest.approx(10.0)


class TestDeadlineModel:
    def test_overdue(self):
        dl = Deadline(title="Test", due_date="2020-01-01")
        assert dl.is_overdue

    def test_not_overdue_if_completed(self):
        dl = Deadline(title="Test", due_date="2020-01-01", is_completed=True)
        assert not dl.is_overdue


class TestRepositories:
    def test_bill_repo_crud(self, db):
        repo = BillRepository(db)
        bill = Bill(name="Test Bill", amount_cents=5000, provider="Test")
        repo.insert(bill)

        fetched = repo.get(bill.id)
        assert fetched.name == "Test Bill"

        updated = repo.update(bill.id, name="Updated Bill")
        assert updated.name == "Updated Bill"

        all_bills = repo.list_all()
        assert len(all_bills) == 1

    def test_not_found(self, db):
        repo = BillRepository(db)
        with pytest.raises(NotFoundError):
            repo.get("nonexistent-id")

    def test_child_repo(self, db):
        repo = ChildRepository(db)
        child = Child(name="Jake")
        repo.insert(child)

        found = repo.find_by_name("jake")
        assert found is not None
        assert found.name == "Jake"
