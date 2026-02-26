"""Morning catchup service — what needs attention NOW."""

from __future__ import annotations

from datetime import date
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.services.account_service import AccountService
from circuitai.services.activity_service import ActivityService
from circuitai.services.bill_service import BillService
from circuitai.services.card_service import CardService
from circuitai.services.deadline_service import DeadlineService
from circuitai.services.subscription_service import SubscriptionService


class MorningService:
    """Generates the morning catchup briefing."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.bills = BillService(db)
        self.accounts = AccountService(db)
        self.cards = CardService(db)
        self.deadlines = DeadlineService(db)
        self.activities = ActivityService(db)
        self.subscriptions = SubscriptionService(db)

    def get_briefing(self) -> dict[str, Any]:
        """Generate the full morning briefing."""
        today = date.today()

        # Attention items
        attention: list[dict[str, Any]] = []

        # Overdue deadlines
        for dl in self.deadlines.get_overdue():
            attention.append({
                "type": "deadline_overdue",
                "title": dl.title,
                "due_date": dl.due_date,
                "priority": dl.priority,
                "id": dl.id,
            })

        # Bills due soon (within 7 days)
        for bill in self.bills.get_due_soon(within_days=7):
            last_payment = self.bills.get_last_payment(bill.id)
            # Check if already paid this period
            if last_payment:
                paid = date.fromisoformat(last_payment.paid_date[:10])
                if (today - paid).days < 25:  # Paid recently, skip
                    continue

            # Calculate actual due date this month
            due_day = bill.due_day or 1
            try:
                due_date = today.replace(day=due_day)
            except ValueError:
                import calendar
                last_day = calendar.monthrange(today.year, today.month)[1]
                due_date = today.replace(day=min(due_day, last_day))

            if due_date < today:
                if today.month == 12:
                    due_date = due_date.replace(year=today.year + 1, month=1)
                else:
                    due_date = due_date.replace(month=today.month + 1)

            days_until = (due_date - today).days
            attention.append({
                "type": "bill_due",
                "title": bill.name,
                "amount_cents": bill.amount_cents,
                "due_date": due_date.isoformat(),
                "days_until": days_until,
                "id": bill.id,
            })

        # Upcoming deadlines (within 3 days)
        for dl in self.deadlines.get_upcoming(within_days=3):
            attention.append({
                "type": "deadline_upcoming",
                "title": dl.title,
                "due_date": dl.due_date,
                "days_until": dl.days_until,
                "priority": dl.priority,
                "id": dl.id,
            })

        # Upcoming subscription charges (within 3 days)
        for sub in self.subscriptions.get_upcoming(within_days=3):
            if sub.next_charge_date:
                charge_date = date.fromisoformat(sub.next_charge_date[:10])
                days_until = (charge_date - today).days
                attention.append({
                    "type": "subscription_charge",
                    "title": sub.name,
                    "amount_cents": sub.amount_cents,
                    "due_date": sub.next_charge_date,
                    "days_until": days_until,
                    "id": sub.id,
                })

        # Sort attention items by urgency
        attention.sort(key=lambda x: x.get("days_until", 999))

        # This week's summary
        bills_this_week = self.bills.get_due_soon(within_days=7)
        week_bill_total = sum(b.amount_cents for b in bills_this_week)
        upcoming_deadlines = self.deadlines.get_upcoming(within_days=7)

        # Accounts snapshot
        acct_snapshot = self.accounts.get_snapshot()
        card_snapshot = self.cards.get_snapshot()

        return {
            "date": today.isoformat(),
            "day_name": today.strftime("%A"),
            "attention_items": attention,
            "attention_count": len(attention),
            "week_summary": {
                "bills_due_cents": week_bill_total,
                "bills_due_count": len(bills_this_week),
                "deadlines_count": len(upcoming_deadlines),
                "subscriptions_monthly_cents": self.subscriptions.get_summary()["monthly_total_cents"],
            },
            "accounts_snapshot": acct_snapshot,
            "cards_snapshot": card_snapshot,
        }
