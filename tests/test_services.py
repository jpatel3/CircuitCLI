"""Tests for various services."""

import tempfile
from pathlib import Path

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.services.account_service import AccountService
from circuitai.services.card_service import CardService
from circuitai.services.investment_service import InvestmentService
from circuitai.services.deadline_service import DeadlineService
from circuitai.services.activity_service import ActivityService
from circuitai.services.mortgage_service import MortgageService


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


class TestAccountService:
    def test_add_and_list(self, db):
        svc = AccountService(db)
        acct = svc.add_account(name="Chase Checking", institution="Chase", balance_cents=520000)
        assert acct.balance_cents == 520000
        accounts = svc.list_accounts()
        assert len(accounts) == 1

    def test_update_balance(self, db):
        svc = AccountService(db)
        acct = svc.add_account(name="Savings", institution="BoA", balance_cents=100000)
        updated = svc.update_balance(acct.id, 150000)
        assert updated.balance_cents == 150000

    def test_total_balance(self, db):
        svc = AccountService(db)
        svc.add_account(name="A1", institution="Chase", balance_cents=100000)
        svc.add_account(name="A2", institution="BoA", balance_cents=200000)
        assert svc.get_total_balance() == 300000


class TestCardService:
    def test_add_card(self, db):
        svc = CardService(db)
        card = svc.add_card(name="Amex", institution="American Express", credit_limit_cents=1000000)
        assert card.name == "Amex"

    def test_total_balance(self, db):
        svc = CardService(db)
        svc.add_card(name="C1", institution="Amex", balance_cents=50000)
        svc.add_card(name="C2", institution="Citi", balance_cents=30000)
        assert svc.get_total_balance() == 80000


class TestInvestmentService:
    def test_add_and_contribute(self, db):
        svc = InvestmentService(db)
        inv = svc.add_investment(name="Wealthfront", institution="Wealthfront", current_value_cents=500000)
        contrib = svc.contribute(inv.id, amount_cents=10000)
        assert contrib.amount_cents == 10000

        # Cost basis should be updated
        updated = svc.get_investment(inv.id)
        assert updated.cost_basis_cents == 10000

    def test_performance(self, db):
        svc = InvestmentService(db)
        svc.add_investment(name="I1", institution="X", current_value_cents=110000, cost_basis_cents=100000)
        perf = svc.get_performance()
        assert perf["total_value_cents"] == 110000
        assert perf["total_gain_loss_cents"] == 10000


class TestDeadlineService:
    def test_add_and_complete(self, db):
        svc = DeadlineService(db)
        dl = svc.add_deadline(title="Pay taxes", due_date="2026-04-15", priority="high")
        assert not dl.is_completed

        completed = svc.complete_deadline(dl.id)
        assert completed.is_completed


class TestActivityService:
    def test_add_child_and_activity(self, db):
        svc = ActivityService(db)
        child = svc.add_child(name="Jake")
        activity = svc.add_activity(name="Hockey", child_id=child.id, sport_or_type="Hockey", cost_cents=35000)
        assert activity.child_id == child.id

        activities = svc.get_for_child(child.id)
        assert len(activities) == 1

    def test_cost_summary(self, db):
        svc = ActivityService(db)
        child = svc.add_child(name="Emma")
        svc.add_activity(name="Gymnastics", child_id=child.id, cost_cents=25000)
        svc.add_activity(name="Tennis", child_id=child.id, cost_cents=15000)
        summary = svc.get_cost_summary()
        assert summary["total_cents"] == 40000


class TestMortgageService:
    def test_add_and_pay(self, db):
        svc = MortgageService(db)
        mtg = svc.add_mortgage(
            name="Home Loan", lender="Townee", original_amount_cents=40000000,
            balance_cents=35000000, interest_rate_bps=650,
            monthly_payment_cents=250000,
        )
        payment = svc.make_payment(mtg.id, principal_cents=100000, interest_cents=150000)
        assert payment.amount_cents == 250000

        # Balance should be reduced
        updated = svc.get_mortgage(mtg.id)
        assert updated.balance_cents == 35000000 - 100000

    def test_amortization(self, db):
        svc = MortgageService(db)
        mtg = svc.add_mortgage(
            name="Test", lender="Bank", original_amount_cents=30000000,
            balance_cents=30000000, interest_rate_bps=600,
            monthly_payment_cents=180000,
        )
        schedule = svc.get_amortization_schedule(mtg.id, months=6)
        assert len(schedule) == 6
        # Balance should decrease each month
        for i in range(1, len(schedule)):
            assert schedule[i]["remaining_balance_cents"] < schedule[i - 1]["remaining_balance_cents"]
