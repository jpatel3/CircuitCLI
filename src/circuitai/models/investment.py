"""Investment account and contribution models."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from circuitai.models.base import BaseRepository, CircuitModel, now_iso


class Investment(CircuitModel):
    """An investment account (brokerage, 401k, 529, IRA, etc.)."""

    name: str
    institution: str
    account_type: str = "brokerage"  # brokerage, 401k, 529, ira, roth_ira, hsa, crypto, other
    current_value_cents: int = 0
    cost_basis_cents: int = 0
    recurring_amount_cents: int = 0
    recurring_frequency: str = "monthly"
    source_account_id: str | None = None
    beneficiary_child_id: str | None = None
    value_updated_at: str | None = None
    notes: str = ""
    is_active: bool = True

    @property
    def current_value_dollars(self) -> float:
        return self.current_value_cents / 100

    @property
    def gain_loss_cents(self) -> int:
        return self.current_value_cents - self.cost_basis_cents

    @property
    def gain_loss_pct(self) -> float:
        if self.cost_basis_cents == 0:
            return 0.0
        return (self.gain_loss_cents / self.cost_basis_cents) * 100

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Investment":
        d = {k: row[k] for k in row.keys()}
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class InvestmentContribution(CircuitModel):
    """A contribution to an investment account."""

    investment_id: str
    amount_cents: int
    contribution_date: str
    source_account_id: str | None = None
    notes: str = ""
    updated_at: str = Field(default="", exclude=True)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "InvestmentContribution":
        d = {k: row[k] for k in row.keys()}
        d.pop("updated_at", None)
        return cls(**d)


class InvestmentRepository(BaseRepository):
    table: ClassVar[str] = "investments"
    model_class: ClassVar[type[CircuitModel]] = Investment  # type: ignore[assignment]

    def get_by_type(self, account_type: str) -> list[Investment]:
        rows = self.db.fetchall(
            "SELECT * FROM investments WHERE account_type = ? AND is_active = 1",
            (account_type,),
        )
        return [Investment.from_row(r) for r in rows]

    def total_value(self) -> int:
        row = self.db.fetchone(
            "SELECT COALESCE(SUM(current_value_cents), 0) as total FROM investments WHERE is_active = 1"
        )
        return row["total"] if row else 0

    def update_value(self, investment_id: str, value_cents: int) -> Investment:
        return self.update(investment_id, current_value_cents=value_cents, value_updated_at=now_iso())  # type: ignore[return-value]


class InvestmentContributionRepository(BaseRepository):
    table: ClassVar[str] = "investment_contributions"
    model_class: ClassVar[type[CircuitModel]] = InvestmentContribution  # type: ignore[assignment]

    def get_for_investment(self, investment_id: str, limit: int = 24) -> list[InvestmentContribution]:
        rows = self.db.fetchall(
            "SELECT * FROM investment_contributions WHERE investment_id = ? ORDER BY contribution_date DESC LIMIT ?",
            (investment_id, limit),
        )
        return [InvestmentContribution.from_row(r) for r in rows]

    def total_contributed(self, investment_id: str) -> int:
        row = self.db.fetchone(
            "SELECT COALESCE(SUM(amount_cents), 0) as total FROM investment_contributions WHERE investment_id = ?",
            (investment_id,),
        )
        return row["total"] if row else 0
