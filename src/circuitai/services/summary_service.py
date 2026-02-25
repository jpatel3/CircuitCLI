"""Cross-domain summary aggregation for dashboard and reports."""

from __future__ import annotations

from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.output.formatter import dollars
from circuitai.services.account_service import AccountService
from circuitai.services.activity_service import ActivityService
from circuitai.services.bill_service import BillService
from circuitai.services.card_service import CardService
from circuitai.services.deadline_service import DeadlineService
from circuitai.services.investment_service import InvestmentService
from circuitai.services.mortgage_service import MortgageService


class SummaryService:
    """Aggregates data across all domains for the dashboard."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.bills = BillService(db)
        self.accounts = AccountService(db)
        self.cards = CardService(db)
        self.mortgages = MortgageService(db)
        self.investments = InvestmentService(db)
        self.deadlines = DeadlineService(db)
        self.activities = ActivityService(db)

    def get_full_summary(self) -> dict[str, Any]:
        """Get a complete financial summary."""
        bill_summary = self.bills.get_summary()
        acct_total = self.accounts.get_total_balance()
        card_total = self.cards.get_total_balance()
        inv_perf = self.investments.get_performance()
        overdue = self.deadlines.get_overdue()
        upcoming_deadlines = self.deadlines.get_upcoming(within_days=7)

        # Net worth estimate
        mortgage_balance = sum(
            m.balance_cents for m in self.mortgages.list_mortgages()
        )
        net_worth = acct_total + inv_perf["total_value_cents"] - card_total - mortgage_balance

        return {
            "net_worth_cents": net_worth,
            "accounts": {
                "total_balance_cents": acct_total,
                "snapshot": self.accounts.get_snapshot(),
            },
            "cards": {
                "total_balance_cents": card_total,
                "total_limit_cents": self.cards.get_total_limit(),
                "snapshot": self.cards.get_snapshot(),
            },
            "bills": bill_summary,
            "investments": inv_perf,
            "mortgage_balance_cents": mortgage_balance,
            "deadlines": {
                "overdue": len(overdue),
                "upcoming_7d": len(upcoming_deadlines),
            },
            "activities": self.activities.get_cost_summary(),
        }
