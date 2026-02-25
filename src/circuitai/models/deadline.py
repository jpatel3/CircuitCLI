"""Deadline model and repository."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, ClassVar

from circuitai.models.base import BaseRepository, CircuitModel, now_iso


class Deadline(CircuitModel):
    """A deadline or due date to track."""

    title: str
    description: str = ""
    due_date: str = ""
    priority: str = "medium"  # low, medium, high, urgent
    category: str = "general"
    linked_bill_id: str | None = None
    is_completed: bool = False
    completed_at: str | None = None
    notes: str = ""

    @property
    def days_until(self) -> int | None:
        if not self.due_date:
            return None
        try:
            due = date.fromisoformat(self.due_date[:10])
            return (due - date.today()).days
        except ValueError:
            return None

    @property
    def is_overdue(self) -> bool:
        days = self.days_until
        return days is not None and days < 0 and not self.is_completed

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_completed"] = int(data["is_completed"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Deadline":
        d = {k: row[k] for k in row.keys()}
        d["is_completed"] = bool(d.get("is_completed", 0))
        return cls(**d)


class DeadlineRepository(BaseRepository):
    table: ClassVar[str] = "deadlines"
    model_class: ClassVar[type[CircuitModel]] = Deadline  # type: ignore[assignment]

    def get_upcoming(self, within_days: int = 14) -> list[Deadline]:
        """Get uncompleted deadlines due within N days."""
        target = date.today().isoformat()
        from datetime import timedelta
        end = (date.today() + timedelta(days=within_days)).isoformat()
        rows = self.db.fetchall(
            "SELECT * FROM deadlines WHERE is_completed = 0 AND due_date >= ? AND due_date <= ? ORDER BY due_date",
            (target, end),
        )
        return [Deadline.from_row(r) for r in rows]

    def get_overdue(self) -> list[Deadline]:
        """Get uncompleted deadlines that are past due."""
        today = date.today().isoformat()
        rows = self.db.fetchall(
            "SELECT * FROM deadlines WHERE is_completed = 0 AND due_date < ? ORDER BY due_date",
            (today,),
        )
        return [Deadline.from_row(r) for r in rows]

    def complete(self, deadline_id: str) -> Deadline:
        return self.update(deadline_id, is_completed=1, completed_at=now_iso())  # type: ignore[return-value]

    def find_by_linked_bill(self, bill_id: str, active_only: bool = True) -> list[Deadline]:
        """Find deadlines linked to a specific bill."""
        sql = "SELECT * FROM deadlines WHERE linked_bill_id = ?"
        if active_only:
            sql += " AND is_completed = 0"
        sql += " ORDER BY due_date"
        rows = self.db.fetchall(sql, (bill_id,))
        return [Deadline.from_row(r) for r in rows]

    def list_all(self, active_only: bool = True) -> list[Deadline]:
        sql = "SELECT * FROM deadlines"
        if active_only:
            sql += " WHERE is_completed = 0"
        sql += " ORDER BY due_date"
        rows = self.db.fetchall(sql)
        return [Deadline.from_row(r) for r in rows]
