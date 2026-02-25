"""Mortgage and payment models."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from circuitai.models.base import BaseRepository, CircuitModel


class Mortgage(CircuitModel):
    """A mortgage loan."""

    name: str
    lender: str
    original_amount_cents: int
    balance_cents: int
    interest_rate_bps: int  # basis points (e.g., 650 = 6.50%)
    monthly_payment_cents: int
    escrow_cents: int = 0
    term_months: int = 360  # 30 years
    start_date: str = ""
    due_day: int = 1
    account_id: str | None = None
    notes: str = ""
    is_active: bool = True

    @property
    def balance_dollars(self) -> float:
        return self.balance_cents / 100

    @property
    def monthly_payment_dollars(self) -> float:
        return self.monthly_payment_cents / 100

    @property
    def interest_rate_pct(self) -> float:
        return self.interest_rate_bps / 100

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Mortgage":
        d = {k: row[k] for k in row.keys()}
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class MortgagePayment(CircuitModel):
    """A mortgage payment record."""

    mortgage_id: str
    amount_cents: int
    principal_cents: int = 0
    interest_cents: int = 0
    escrow_cents: int = 0
    paid_date: str = ""
    notes: str = ""
    updated_at: str = Field(default="", exclude=True)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "MortgagePayment":
        d = {k: row[k] for k in row.keys()}
        d.pop("updated_at", None)
        return cls(**d)


class MortgageRepository(BaseRepository):
    table: ClassVar[str] = "mortgages"
    model_class: ClassVar[type[CircuitModel]] = Mortgage  # type: ignore[assignment]


class MortgagePaymentRepository(BaseRepository):
    table: ClassVar[str] = "mortgage_payments"
    model_class: ClassVar[type[CircuitModel]] = MortgagePayment  # type: ignore[assignment]

    def get_for_mortgage(self, mortgage_id: str, limit: int = 24) -> list[MortgagePayment]:
        rows = self.db.fetchall(
            "SELECT * FROM mortgage_payments WHERE mortgage_id = ? ORDER BY paid_date DESC LIMIT ?",
            (mortgage_id, limit),
        )
        return [MortgagePayment.from_row(r) for r in rows]

    def total_paid(self, mortgage_id: str) -> dict[str, int]:
        row = self.db.fetchone(
            """SELECT COALESCE(SUM(amount_cents), 0) as total,
                      COALESCE(SUM(principal_cents), 0) as principal,
                      COALESCE(SUM(interest_cents), 0) as interest
               FROM mortgage_payments WHERE mortgage_id = ?""",
            (mortgage_id,),
        )
        if row:
            return {"total": row["total"], "principal": row["principal"], "interest": row["interest"]}
        return {"total": 0, "principal": 0, "interest": 0}
