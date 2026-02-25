"""Kids activity and children models."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from circuitai.models.base import BaseRepository, CircuitModel


class Child(CircuitModel):
    """A child in the family."""

    name: str
    birth_date: str | None = None
    notes: str = ""

    @classmethod
    def from_row(cls, row: Any) -> "Child":
        d = {k: row[k] for k in row.keys()}
        return cls(**d)


class Activity(CircuitModel):
    """A kids' activity (sports, lessons, etc.)."""

    name: str
    child_id: str | None = None
    sport_or_type: str = ""
    provider: str = ""
    season: str = ""
    cost_cents: int = 0
    frequency: str = ""  # weekly, biweekly, etc.
    schedule: str = ""  # e.g., "Mon/Wed 5-6pm"
    location: str = ""
    notes: str = ""
    is_active: bool = True

    @property
    def cost_dollars(self) -> float:
        return self.cost_cents / 100

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Activity":
        d = {k: row[k] for k in row.keys()}
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class ActivityPayment(CircuitModel):
    """A payment for an activity (registration, fees, etc.)."""

    activity_id: str
    amount_cents: int
    paid_date: str
    description: str = ""
    notes: str = ""
    updated_at: str = Field(default="", exclude=True)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "ActivityPayment":
        d = {k: row[k] for k in row.keys()}
        d.pop("updated_at", None)
        return cls(**d)


class ChildRepository(BaseRepository):
    table: ClassVar[str] = "children"
    model_class: ClassVar[type[CircuitModel]] = Child  # type: ignore[assignment]

    def find_by_name(self, name: str) -> Child | None:
        row = self.db.fetchone(
            "SELECT * FROM children WHERE LOWER(name) LIKE ?",
            (f"%{name.lower()}%",),
        )
        return Child.from_row(row) if row else None

    def list_all(self, active_only: bool = True) -> list[Child]:
        rows = self.db.fetchall("SELECT * FROM children ORDER BY name")
        return [Child.from_row(r) for r in rows]


class ActivityRepository(BaseRepository):
    table: ClassVar[str] = "activities"
    model_class: ClassVar[type[CircuitModel]] = Activity  # type: ignore[assignment]

    def get_for_child(self, child_id: str) -> list[Activity]:
        rows = self.db.fetchall(
            "SELECT * FROM activities WHERE child_id = ? AND is_active = 1 ORDER BY name",
            (child_id,),
        )
        return [Activity.from_row(r) for r in rows]

    def get_by_sport(self, sport: str) -> list[Activity]:
        rows = self.db.fetchall(
            "SELECT * FROM activities WHERE LOWER(sport_or_type) LIKE ? AND is_active = 1",
            (f"%{sport.lower()}%",),
        )
        return [Activity.from_row(r) for r in rows]

    def total_cost(self, child_id: str | None = None) -> int:
        sql = "SELECT COALESCE(SUM(cost_cents), 0) as total FROM activities WHERE is_active = 1"
        params: tuple = ()
        if child_id:
            sql += " AND child_id = ?"
            params = (child_id,)
        row = self.db.fetchone(sql, params)
        return row["total"] if row else 0


class ActivityPaymentRepository(BaseRepository):
    table: ClassVar[str] = "activity_payments"
    model_class: ClassVar[type[CircuitModel]] = ActivityPayment  # type: ignore[assignment]

    def get_for_activity(self, activity_id: str, limit: int = 20) -> list[ActivityPayment]:
        rows = self.db.fetchall(
            "SELECT * FROM activity_payments WHERE activity_id = ? ORDER BY paid_date DESC LIMIT ?",
            (activity_id, limit),
        )
        return [ActivityPayment.from_row(r) for r in rows]
