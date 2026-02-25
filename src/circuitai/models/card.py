"""Credit card and transaction models."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from circuitai.models.base import BaseRepository, CircuitModel, new_id, now_iso


class Card(CircuitModel):
    """A credit card."""

    name: str
    institution: str
    last_four: str = ""
    credit_limit_cents: int = 0
    balance_cents: int = 0
    due_day: int | None = None
    apr_bps: int = 0  # basis points (e.g., 2499 = 24.99%)
    balance_updated_at: str | None = None
    notes: str = ""
    is_active: bool = True

    @property
    def balance_dollars(self) -> float:
        return self.balance_cents / 100

    @property
    def limit_dollars(self) -> float:
        return self.credit_limit_cents / 100

    @property
    def utilization_pct(self) -> float:
        if self.credit_limit_cents == 0:
            return 0.0
        return (self.balance_cents / self.credit_limit_cents) * 100

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Card":
        d = {k: row[k] for k in row.keys()}
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class CardTransaction(CircuitModel):
    """A transaction on a credit card."""

    card_id: str
    description: str
    amount_cents: int
    transaction_date: str
    category: str = ""
    linked_bill_id: str | None = None
    is_matched: bool = False
    updated_at: str = Field(default="", exclude=True)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_matched"] = int(data["is_matched"])
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "CardTransaction":
        d = {k: row[k] for k in row.keys()}
        d["is_matched"] = bool(d.get("is_matched", 0))
        d.pop("updated_at", None)
        return cls(**d)


class CardRepository(BaseRepository):
    table: ClassVar[str] = "cards"
    model_class: ClassVar[type[CircuitModel]] = Card  # type: ignore[assignment]

    def update_balance(self, card_id: str, balance_cents: int) -> Card:
        return self.update(card_id, balance_cents=balance_cents, balance_updated_at=now_iso())  # type: ignore[return-value]


class CardTransactionRepository(BaseRepository):
    table: ClassVar[str] = "card_transactions"
    model_class: ClassVar[type[CircuitModel]] = CardTransaction  # type: ignore[assignment]

    def get_for_card(self, card_id: str, limit: int = 50) -> list[CardTransaction]:
        rows = self.db.fetchall(
            "SELECT * FROM card_transactions WHERE card_id = ? ORDER BY transaction_date DESC LIMIT ?",
            (card_id, limit),
        )
        return [CardTransaction.from_row(r) for r in rows]

    def get_unmatched(self, card_id: str | None = None) -> list[CardTransaction]:
        sql = "SELECT * FROM card_transactions WHERE is_matched = 0"
        params: tuple = ()
        if card_id:
            sql += " AND card_id = ?"
            params = (card_id,)
        sql += " ORDER BY transaction_date DESC"
        rows = self.db.fetchall(sql, params)
        return [CardTransaction.from_row(r) for r in rows]
