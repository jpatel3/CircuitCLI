"""Bank account management business logic."""

from __future__ import annotations

from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ValidationError
from circuitai.models.account import (
    Account,
    AccountRepository,
    AccountTransaction,
    AccountTransactionRepository,
)
from circuitai.models.base import now_iso


class AccountService:
    """Business logic for bank account operations."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.accounts = AccountRepository(db)
        self.transactions = AccountTransactionRepository(db)

    def add_account(
        self,
        name: str,
        institution: str,
        account_type: str = "checking",
        last_four: str = "",
        balance_cents: int = 0,
        notes: str = "",
    ) -> Account:
        if not name:
            raise ValidationError("Account name is required.")
        if not institution:
            raise ValidationError("Institution is required.")

        acct = Account(
            name=name,
            institution=institution,
            account_type=account_type,
            last_four=last_four,
            balance_cents=balance_cents,
            balance_updated_at=now_iso() if balance_cents else None,
            notes=notes,
        )
        self.accounts.insert(acct)
        return acct

    def get_account(self, account_id: str) -> Account:
        return self.accounts.get(account_id)  # type: ignore[return-value]

    def list_accounts(self, active_only: bool = True) -> list[Account]:
        return self.accounts.list_all(active_only=active_only)  # type: ignore[return-value]

    def update_balance(self, account_id: str, balance_cents: int) -> Account:
        return self.accounts.update_balance(account_id, balance_cents)

    def update_account(self, account_id: str, **updates: Any) -> Account:
        return self.accounts.update(account_id, **updates)  # type: ignore[return-value]

    def delete_account(self, account_id: str) -> None:
        self.accounts.soft_delete(account_id)

    def add_transaction(
        self,
        account_id: str,
        description: str,
        amount_cents: int,
        transaction_date: str,
        category: str = "",
    ) -> AccountTransaction:
        txn = AccountTransaction(
            account_id=account_id,
            description=description,
            amount_cents=amount_cents,
            transaction_date=transaction_date,
            category=category,
        )
        self.transactions.insert(txn)
        return txn

    def get_transactions(self, account_id: str, limit: int = 50) -> list[AccountTransaction]:
        return self.transactions.get_for_account(account_id, limit=limit)

    def get_unmatched_transactions(self, account_id: str | None = None) -> list[AccountTransaction]:
        return self.transactions.get_unmatched(account_id=account_id)

    def get_total_balance(self) -> int:
        """Sum of all active account balances."""
        accounts = self.list_accounts()
        return sum(a.balance_cents for a in accounts)

    def get_snapshot(self) -> list[dict[str, Any]]:
        """Get a quick snapshot of all accounts."""
        accounts = self.list_accounts()
        return [
            {
                "id": a.id,
                "name": a.name,
                "institution": a.institution,
                "type": a.account_type,
                "last_four": a.last_four,
                "balance_cents": a.balance_cents,
            }
            for a in accounts
        ]
