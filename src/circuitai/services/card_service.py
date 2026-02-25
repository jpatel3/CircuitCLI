"""Credit card management business logic."""

from __future__ import annotations

from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ValidationError
from circuitai.models.base import now_iso
from circuitai.models.card import Card, CardRepository, CardTransaction, CardTransactionRepository


class CardService:
    """Business logic for credit card operations."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.cards = CardRepository(db)
        self.transactions = CardTransactionRepository(db)

    def add_card(
        self,
        name: str,
        institution: str,
        last_four: str = "",
        credit_limit_cents: int = 0,
        balance_cents: int = 0,
        due_day: int | None = None,
        apr_bps: int = 0,
        notes: str = "",
    ) -> Card:
        if not name:
            raise ValidationError("Card name is required.")

        card = Card(
            name=name,
            institution=institution,
            last_four=last_four,
            credit_limit_cents=credit_limit_cents,
            balance_cents=balance_cents,
            due_day=due_day,
            apr_bps=apr_bps,
            balance_updated_at=now_iso() if balance_cents else None,
            notes=notes,
        )
        self.cards.insert(card)
        return card

    def get_card(self, card_id: str) -> Card:
        return self.cards.get(card_id)  # type: ignore[return-value]

    def list_cards(self, active_only: bool = True) -> list[Card]:
        return self.cards.list_all(active_only=active_only)  # type: ignore[return-value]

    def update_balance(self, card_id: str, balance_cents: int) -> Card:
        return self.cards.update_balance(card_id, balance_cents)

    def update_card(self, card_id: str, **updates: Any) -> Card:
        return self.cards.update(card_id, **updates)  # type: ignore[return-value]

    def delete_card(self, card_id: str) -> None:
        self.cards.soft_delete(card_id)

    def add_transaction(
        self,
        card_id: str,
        description: str,
        amount_cents: int,
        transaction_date: str,
        category: str = "",
    ) -> CardTransaction:
        txn = CardTransaction(
            card_id=card_id,
            description=description,
            amount_cents=amount_cents,
            transaction_date=transaction_date,
            category=category,
        )
        self.transactions.insert(txn)
        return txn

    def get_transactions(self, card_id: str, limit: int = 50) -> list[CardTransaction]:
        return self.transactions.get_for_card(card_id, limit=limit)

    def get_total_balance(self) -> int:
        cards = self.list_cards()
        return sum(c.balance_cents for c in cards)

    def get_total_limit(self) -> int:
        cards = self.list_cards()
        return sum(c.credit_limit_cents for c in cards)

    def get_snapshot(self) -> list[dict[str, Any]]:
        cards = self.list_cards()
        return [
            {
                "id": c.id,
                "name": c.name,
                "institution": c.institution,
                "last_four": c.last_four,
                "balance_cents": c.balance_cents,
                "limit_cents": c.credit_limit_cents,
                "utilization_pct": round(c.utilization_pct, 1),
            }
            for c in cards
        ]
