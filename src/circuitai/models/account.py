"""Bank account and transaction models."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from circuitai.models.base import BaseRepository, CircuitModel, now_iso


class Account(CircuitModel):
    """A bank account (checking, savings, etc.)."""

    name: str
    institution: str
    account_type: str = "checking"  # checking, savings, money_market
    last_four: str = ""
    balance_cents: int = 0
    balance_updated_at: str | None = None
    notes: str = ""
    is_active: bool = True

    @property
    def balance_dollars(self) -> float:
        return self.balance_cents / 100

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Account":
        d = {k: row[k] for k in row.keys()}
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class AccountTransaction(CircuitModel):
    """A transaction on a bank account."""

    account_id: str
    description: str
    amount_cents: int  # negative = debit, positive = credit
    transaction_date: str
    category: str = ""
    linked_bill_id: str | None = None
    linked_investment_id: str | None = None
    is_matched: bool = False
    updated_at: str = Field(default="", exclude=True)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_matched"] = int(data["is_matched"])
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "AccountTransaction":
        d = {k: row[k] for k in row.keys()}
        d["is_matched"] = bool(d.get("is_matched", 0))
        d.pop("updated_at", None)
        return cls(**d)


class AccountRepository(BaseRepository):
    table: ClassVar[str] = "accounts"
    model_class: ClassVar[type[CircuitModel]] = Account  # type: ignore[assignment]

    def find_by_institution(self, institution: str) -> list[Account]:
        rows = self.db.fetchall(
            "SELECT * FROM accounts WHERE LOWER(institution) LIKE ? AND is_active = 1",
            (f"%{institution.lower()}%",),
        )
        return [Account.from_row(r) for r in rows]

    def update_balance(self, account_id: str, balance_cents: int) -> Account:
        return self.update(account_id, balance_cents=balance_cents, balance_updated_at=now_iso())  # type: ignore[return-value]


class AccountTransactionRepository(BaseRepository):
    table: ClassVar[str] = "account_transactions"
    model_class: ClassVar[type[CircuitModel]] = AccountTransaction  # type: ignore[assignment]

    def get_for_account(self, account_id: str, limit: int = 50) -> list[AccountTransaction]:
        rows = self.db.fetchall(
            "SELECT * FROM account_transactions WHERE account_id = ? ORDER BY transaction_date DESC LIMIT ?",
            (account_id, limit),
        )
        return [AccountTransaction.from_row(r) for r in rows]

    def get_unmatched(self, account_id: str | None = None) -> list[AccountTransaction]:
        sql = "SELECT * FROM account_transactions WHERE is_matched = 0"
        params: tuple = ()
        if account_id:
            sql += " AND account_id = ?"
            params = (account_id,)
        sql += " ORDER BY transaction_date DESC"
        rows = self.db.fetchall(sql, params)
        return [AccountTransaction.from_row(r) for r in rows]
