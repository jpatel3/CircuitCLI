"""Bill management business logic."""

from __future__ import annotations

from datetime import date
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import NotFoundError, ValidationError
from circuitai.models.base import now_iso
from circuitai.models.bill import Bill, BillPayment, BillPaymentRepository, BillRepository


class BillService:
    """Business logic for bill operations."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.bills = BillRepository(db)
        self.payments = BillPaymentRepository(db)

    def add_bill(
        self,
        name: str,
        provider: str = "",
        category: str = "other",
        amount_cents: int = 0,
        due_day: int | None = None,
        frequency: str = "monthly",
        account_id: str | None = None,
        auto_pay: bool = False,
        notes: str = "",
    ) -> Bill:
        """Add a new bill."""
        if not name:
            raise ValidationError("Bill name is required.")
        if amount_cents < 0:
            raise ValidationError("Amount cannot be negative.")
        if due_day is not None and not (1 <= due_day <= 31):
            raise ValidationError("Due day must be between 1 and 31.")

        bill = Bill(
            name=name,
            provider=provider or name,
            category=category,
            amount_cents=amount_cents,
            due_day=due_day,
            frequency=frequency,
            account_id=account_id,
            auto_pay=auto_pay,
            notes=notes,
        )
        # Seed match patterns from provider name
        if provider:
            bill.add_pattern(provider.upper())

        self.bills.insert(bill)
        return bill

    def get_bill(self, bill_id: str) -> Bill:
        return self.bills.get(bill_id)  # type: ignore[return-value]

    def list_bills(self, active_only: bool = True) -> list[Bill]:
        return self.bills.list_all(active_only=active_only)  # type: ignore[return-value]

    def search_bills(self, query: str) -> list[Bill]:
        return self.bills.find_by_name(query)

    def update_bill(self, bill_id: str, **updates: Any) -> Bill:
        return self.bills.update(bill_id, **updates)  # type: ignore[return-value]

    def delete_bill(self, bill_id: str) -> None:
        self.bills.soft_delete(bill_id)

    def pay_bill(
        self,
        bill_id: str,
        amount_cents: int | None = None,
        paid_date: str | None = None,
        payment_method: str = "",
        confirmation: str = "",
        notes: str = "",
    ) -> BillPayment:
        """Record a payment for a bill."""
        bill = self.get_bill(bill_id)
        if amount_cents is None:
            amount_cents = bill.amount_cents
        if paid_date is None:
            paid_date = date.today().isoformat()

        payment = BillPayment(
            bill_id=bill_id,
            amount_cents=amount_cents,
            paid_date=paid_date,
            payment_method=payment_method,
            confirmation=confirmation,
            notes=notes,
        )
        self.payments.insert(payment)
        return payment

    def get_payments(self, bill_id: str, limit: int = 10) -> list[BillPayment]:
        return self.payments.get_for_bill(bill_id, limit=limit)

    def get_last_payment(self, bill_id: str) -> BillPayment | None:
        return self.payments.get_last_payment(bill_id)

    def get_due_soon(self, within_days: int = 7) -> list[Bill]:
        return self.bills.get_due_soon(within_days=within_days)

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of all bills."""
        bills = self.list_bills()
        total_monthly = sum(b.amount_cents for b in bills if b.frequency == "monthly")
        total_yearly = sum(b.amount_cents for b in bills if b.frequency == "yearly")
        total_quarterly = sum(b.amount_cents for b in bills if b.frequency == "quarterly")
        due_soon = self.get_due_soon(within_days=7)

        return {
            "total_bills": len(bills),
            "monthly_total_cents": total_monthly,
            "yearly_total_cents": total_yearly,
            "quarterly_total_cents": total_quarterly,
            "estimated_monthly_cents": total_monthly + (total_yearly // 12) + (total_quarterly // 3),
            "due_soon": len(due_soon),
            "due_soon_bills": [{"name": b.name, "amount_cents": b.amount_cents, "due_day": b.due_day} for b in due_soon],
        }
