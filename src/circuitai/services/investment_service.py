"""Investment account management business logic."""

from __future__ import annotations

from datetime import date
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ValidationError
from circuitai.models.base import now_iso
from circuitai.models.investment import (
    Investment,
    InvestmentContribution,
    InvestmentContributionRepository,
    InvestmentRepository,
)


class InvestmentService:
    """Business logic for investment operations."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.investments = InvestmentRepository(db)
        self.contributions = InvestmentContributionRepository(db)

    def add_investment(
        self,
        name: str,
        institution: str,
        account_type: str = "brokerage",
        current_value_cents: int = 0,
        cost_basis_cents: int = 0,
        recurring_amount_cents: int = 0,
        recurring_frequency: str = "monthly",
        source_account_id: str | None = None,
        beneficiary_child_id: str | None = None,
        notes: str = "",
    ) -> Investment:
        if not name:
            raise ValidationError("Investment name is required.")

        inv = Investment(
            name=name,
            institution=institution,
            account_type=account_type,
            current_value_cents=current_value_cents,
            cost_basis_cents=cost_basis_cents,
            recurring_amount_cents=recurring_amount_cents,
            recurring_frequency=recurring_frequency,
            source_account_id=source_account_id,
            beneficiary_child_id=beneficiary_child_id,
            value_updated_at=now_iso() if current_value_cents else None,
            notes=notes,
        )
        self.investments.insert(inv)
        return inv

    def get_investment(self, investment_id: str) -> Investment:
        return self.investments.get(investment_id)  # type: ignore[return-value]

    def list_investments(self, active_only: bool = True) -> list[Investment]:
        return self.investments.list_all(active_only=active_only)  # type: ignore[return-value]

    def get_by_type(self, account_type: str) -> list[Investment]:
        return self.investments.get_by_type(account_type)

    def update_value(self, investment_id: str, value_cents: int) -> Investment:
        return self.investments.update_value(investment_id, value_cents)

    def update_investment(self, investment_id: str, **updates: Any) -> Investment:
        return self.investments.update(investment_id, **updates)  # type: ignore[return-value]

    def delete_investment(self, investment_id: str) -> None:
        self.investments.soft_delete(investment_id)

    def contribute(
        self,
        investment_id: str,
        amount_cents: int,
        contribution_date: str | None = None,
        source_account_id: str | None = None,
        notes: str = "",
    ) -> InvestmentContribution:
        contrib = InvestmentContribution(
            investment_id=investment_id,
            amount_cents=amount_cents,
            contribution_date=contribution_date or date.today().isoformat(),
            source_account_id=source_account_id,
            notes=notes,
        )
        self.contributions.insert(contrib)

        # Update cost basis
        inv = self.get_investment(investment_id)
        self.investments.update(
            investment_id,
            cost_basis_cents=inv.cost_basis_cents + amount_cents,
        )
        return contrib

    def get_contributions(self, investment_id: str, limit: int = 24) -> list[InvestmentContribution]:
        return self.contributions.get_for_investment(investment_id, limit=limit)

    def get_total_value(self) -> int:
        return self.investments.total_value()

    def get_performance(self) -> dict[str, Any]:
        """Get overall investment performance summary."""
        investments = self.list_investments()
        total_value = sum(i.current_value_cents for i in investments)
        total_cost = sum(i.cost_basis_cents for i in investments)
        total_gain = total_value - total_cost
        gain_pct = (total_gain / total_cost * 100) if total_cost > 0 else 0

        by_type: dict[str, int] = {}
        for inv in investments:
            by_type[inv.account_type] = by_type.get(inv.account_type, 0) + inv.current_value_cents

        return {
            "total_value_cents": total_value,
            "total_cost_basis_cents": total_cost,
            "total_gain_loss_cents": total_gain,
            "gain_loss_pct": round(gain_pct, 2),
            "by_type": by_type,
            "count": len(investments),
        }
