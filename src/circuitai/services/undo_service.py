"""Undo service — tracks the last action and allows reversal."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class UndoAction:
    """Represents a reversible action."""

    action_type: str  # "add", "pay", "complete", "update", "delete"
    entity_type: str  # "bill", "account", "card", "deadline", "activity", etc.
    entity_id: str
    description: str  # Human-readable description
    previous_state: dict[str, Any] = field(default_factory=dict)


class UndoService:
    """Manages undo history (single-level undo)."""

    def __init__(self, db) -> None:
        self.db = db
        self._last_action: UndoAction | None = None

    def record(self, action: UndoAction) -> None:
        """Record an action that can be undone."""
        self._last_action = action

    @property
    def has_undo(self) -> bool:
        return self._last_action is not None

    @property
    def last_description(self) -> str:
        if self._last_action:
            return self._last_action.description
        return ""

    def undo(self) -> str:
        """Undo the last recorded action. Returns a description of what was undone."""
        if self._last_action is None:
            return "Nothing to undo."

        action = self._last_action
        self._last_action = None

        if action.action_type == "add":
            return self._undo_add(action)
        elif action.action_type == "pay":
            return self._undo_pay(action)
        elif action.action_type == "complete":
            return self._undo_complete(action)
        elif action.action_type == "delete":
            return self._undo_delete(action)
        elif action.action_type == "update":
            return self._undo_update(action)
        else:
            return f"Cannot undo action type: {action.action_type}"

    def _undo_add(self, action: UndoAction) -> str:
        """Undo an add by deleting the entity."""
        table_map = {
            "bill": "bills",
            "account": "accounts",
            "card": "cards",
            "deadline": "deadlines",
            "activity": "activities",
            "investment": "investments",
            "mortgage": "mortgages",
            "child": "children",
        }
        table = table_map.get(action.entity_type)
        if not table:
            return f"Cannot undo add for {action.entity_type}"

        self.db.execute(f"DELETE FROM {table} WHERE id = ?", (action.entity_id,))
        self.db.commit()
        return f"Undone: {action.description}"

    def _undo_pay(self, action: UndoAction) -> str:
        """Undo a payment by deleting the payment record."""
        payment_table_map = {
            "bill": "bill_payments",
            "mortgage": "mortgage_payments",
            "activity": "activity_payments",
        }
        table = payment_table_map.get(action.entity_type)
        if not table:
            return f"Cannot undo payment for {action.entity_type}"

        # entity_id here is the payment ID
        self.db.execute(f"DELETE FROM {table} WHERE id = ?", (action.entity_id,))
        self.db.commit()
        return f"Undone: {action.description}"

    def _undo_complete(self, action: UndoAction) -> str:
        """Undo a completion by marking as incomplete."""
        if action.entity_type == "deadline":
            self.db.execute(
                "UPDATE deadlines SET is_completed = 0, completed_at = NULL WHERE id = ?",
                (action.entity_id,),
            )
            self.db.commit()
            return f"Undone: {action.description}"
        return f"Cannot undo complete for {action.entity_type}"

    def _undo_delete(self, action: UndoAction) -> str:
        """Undo a soft delete by reactivating."""
        table_map = {
            "bill": ("bills", "is_active"),
            "account": ("accounts", "is_active"),
            "card": ("cards", "is_active"),
            "investment": ("investments", "is_active"),
        }
        info = table_map.get(action.entity_type)
        if not info:
            return f"Cannot undo delete for {action.entity_type}"

        table, col = info
        self.db.execute(f"UPDATE {table} SET {col} = 1 WHERE id = ?", (action.entity_id,))
        self.db.commit()
        return f"Undone: {action.description}"

    def _undo_update(self, action: UndoAction) -> str:
        """Undo an update by restoring previous state."""
        table_map = {
            "bill": "bills",
            "account": "accounts",
            "card": "cards",
            "deadline": "deadlines",
            "activity": "activities",
            "investment": "investments",
        }
        table = table_map.get(action.entity_type)
        if not table or not action.previous_state:
            return f"Cannot undo update for {action.entity_type}"

        cols = ", ".join(f"{k} = ?" for k in action.previous_state)
        vals = list(action.previous_state.values()) + [action.entity_id]
        self.db.execute(f"UPDATE {table} SET {cols} WHERE id = ?", tuple(vals))
        self.db.commit()
        return f"Undone: {action.description}"
