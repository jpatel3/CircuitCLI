"""Mortgage management business logic."""

from __future__ import annotations

from datetime import date
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ValidationError
from circuitai.models.mortgage import (
    Mortgage,
    MortgagePayment,
    MortgagePaymentRepository,
    MortgageRepository,
)


class MortgageService:
    """Business logic for mortgage operations."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.mortgages = MortgageRepository(db)
        self.payments = MortgagePaymentRepository(db)

    def add_mortgage(
        self,
        name: str,
        lender: str,
        original_amount_cents: int,
        balance_cents: int,
        interest_rate_bps: int,
        monthly_payment_cents: int,
        escrow_cents: int = 0,
        term_months: int = 360,
        start_date: str = "",
        due_day: int = 1,
        account_id: str | None = None,
        notes: str = "",
    ) -> Mortgage:
        if not name:
            raise ValidationError("Mortgage name is required.")

        mtg = Mortgage(
            name=name,
            lender=lender,
            original_amount_cents=original_amount_cents,
            balance_cents=balance_cents,
            interest_rate_bps=interest_rate_bps,
            monthly_payment_cents=monthly_payment_cents,
            escrow_cents=escrow_cents,
            term_months=term_months,
            start_date=start_date or date.today().isoformat(),
            due_day=due_day,
            account_id=account_id,
            notes=notes,
        )
        self.mortgages.insert(mtg)
        return mtg

    def get_mortgage(self, mortgage_id: str) -> Mortgage:
        return self.mortgages.get(mortgage_id)  # type: ignore[return-value]

    def list_mortgages(self, active_only: bool = True) -> list[Mortgage]:
        return self.mortgages.list_all(active_only=active_only)  # type: ignore[return-value]

    def update_mortgage(self, mortgage_id: str, **updates: Any) -> Mortgage:
        return self.mortgages.update(mortgage_id, **updates)  # type: ignore[return-value]

    def make_payment(
        self,
        mortgage_id: str,
        amount_cents: int | None = None,
        principal_cents: int = 0,
        interest_cents: int = 0,
        escrow_cents: int = 0,
        paid_date: str | None = None,
        notes: str = "",
    ) -> MortgagePayment:
        mtg = self.get_mortgage(mortgage_id)
        if amount_cents is None:
            amount_cents = mtg.monthly_payment_cents

        payment = MortgagePayment(
            mortgage_id=mortgage_id,
            amount_cents=amount_cents,
            principal_cents=principal_cents,
            interest_cents=interest_cents,
            escrow_cents=escrow_cents,
            paid_date=paid_date or date.today().isoformat(),
            notes=notes,
        )
        self.payments.insert(payment)

        # Update balance if principal is provided
        if principal_cents > 0:
            new_balance = max(0, mtg.balance_cents - principal_cents)
            self.mortgages.update(mortgage_id, balance_cents=new_balance)

        return payment

    def get_payments(self, mortgage_id: str, limit: int = 24) -> list[MortgagePayment]:
        return self.payments.get_for_mortgage(mortgage_id, limit=limit)

    def get_amortization_schedule(self, mortgage_id: str, months: int = 12) -> list[dict[str, Any]]:
        """Generate a simplified amortization schedule for the next N months."""
        mtg = self.get_mortgage(mortgage_id)
        balance = mtg.balance_cents
        monthly_rate = (mtg.interest_rate_bps / 10000) / 12
        payment = mtg.monthly_payment_cents - mtg.escrow_cents  # P&I only

        schedule = []
        for month in range(1, months + 1):
            interest = int(balance * monthly_rate)
            principal = payment - interest
            if principal > balance:
                principal = balance
            balance = max(0, balance - principal)

            schedule.append({
                "month": month,
                "payment_cents": payment + mtg.escrow_cents,
                "principal_cents": principal,
                "interest_cents": interest,
                "escrow_cents": mtg.escrow_cents,
                "remaining_balance_cents": balance,
            })
            if balance == 0:
                break

        return schedule
