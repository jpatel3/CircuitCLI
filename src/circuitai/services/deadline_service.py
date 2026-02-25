"""Deadline management business logic."""

from __future__ import annotations

from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ValidationError
from circuitai.models.deadline import Deadline, DeadlineRepository


class DeadlineService:
    """Business logic for deadline operations."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.deadlines = DeadlineRepository(db)

    def add_deadline(
        self,
        title: str,
        due_date: str,
        description: str = "",
        priority: str = "medium",
        category: str = "general",
        linked_bill_id: str | None = None,
        notes: str = "",
    ) -> Deadline:
        if not title:
            raise ValidationError("Deadline title is required.")
        if not due_date:
            raise ValidationError("Due date is required.")

        dl = Deadline(
            title=title,
            description=description,
            due_date=due_date,
            priority=priority,
            category=category,
            linked_bill_id=linked_bill_id,
            notes=notes,
        )
        self.deadlines.insert(dl)
        return dl

    def get_deadline(self, deadline_id: str) -> Deadline:
        return self.deadlines.get(deadline_id)  # type: ignore[return-value]

    def list_deadlines(self, active_only: bool = True) -> list[Deadline]:
        return self.deadlines.list_all(active_only=active_only)  # type: ignore[return-value]

    def update_deadline(self, deadline_id: str, **updates: Any) -> Deadline:
        return self.deadlines.update(deadline_id, **updates)  # type: ignore[return-value]

    def complete_deadline(self, deadline_id: str) -> Deadline:
        return self.deadlines.complete(deadline_id)

    def delete_deadline(self, deadline_id: str) -> None:
        self.deadlines.delete(deadline_id)

    def get_upcoming(self, within_days: int = 14) -> list[Deadline]:
        return self.deadlines.get_upcoming(within_days=within_days)

    def get_overdue(self) -> list[Deadline]:
        return self.deadlines.get_overdue()

    def create_from_bill(self, bill_id: str, bill_name: str, due_date: str) -> Deadline:
        """Auto-create a deadline from a bill due date."""
        return self.add_deadline(
            title=f"Pay {bill_name}",
            due_date=due_date,
            category="bill",
            linked_bill_id=bill_id,
            priority="high",
        )
