"""Kids activity management business logic."""

from __future__ import annotations

from datetime import date
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ValidationError
from circuitai.models.activity import (
    Activity,
    ActivityPayment,
    ActivityPaymentRepository,
    ActivityRepository,
    Child,
    ChildRepository,
)


class ActivityService:
    """Business logic for kids' activities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.activities = ActivityRepository(db)
        self.payments = ActivityPaymentRepository(db)
        self.children = ChildRepository(db)

    # ── Children ─────────────────────────────────────────────

    def add_child(self, name: str, birth_date: str | None = None, notes: str = "") -> Child:
        if not name:
            raise ValidationError("Child name is required.")
        child = Child(name=name, birth_date=birth_date, notes=notes)
        self.children.insert(child)
        return child

    def get_child(self, child_id: str) -> Child:
        return self.children.get(child_id)  # type: ignore[return-value]

    def list_children(self) -> list[Child]:
        return self.children.list_all()  # type: ignore[return-value]

    def find_child(self, name: str) -> Child | None:
        return self.children.find_by_name(name)

    # ── Activities ───────────────────────────────────────────

    def add_activity(
        self,
        name: str,
        child_id: str | None = None,
        sport_or_type: str = "",
        provider: str = "",
        season: str = "",
        cost_cents: int = 0,
        frequency: str = "",
        schedule: str = "",
        location: str = "",
        notes: str = "",
    ) -> Activity:
        if not name:
            raise ValidationError("Activity name is required.")

        activity = Activity(
            name=name,
            child_id=child_id,
            sport_or_type=sport_or_type or name,
            provider=provider,
            season=season,
            cost_cents=cost_cents,
            frequency=frequency,
            schedule=schedule,
            location=location,
            notes=notes,
        )
        self.activities.insert(activity)
        return activity

    def get_activity(self, activity_id: str) -> Activity:
        return self.activities.get(activity_id)  # type: ignore[return-value]

    def list_activities(self, active_only: bool = True) -> list[Activity]:
        return self.activities.list_all(active_only=active_only)  # type: ignore[return-value]

    def get_for_child(self, child_id: str) -> list[Activity]:
        return self.activities.get_for_child(child_id)

    def update_activity(self, activity_id: str, **updates: Any) -> Activity:
        return self.activities.update(activity_id, **updates)  # type: ignore[return-value]

    def delete_activity(self, activity_id: str) -> None:
        self.activities.soft_delete(activity_id)

    def pay_activity(
        self,
        activity_id: str,
        amount_cents: int,
        paid_date: str | None = None,
        description: str = "",
        notes: str = "",
    ) -> ActivityPayment:
        payment = ActivityPayment(
            activity_id=activity_id,
            amount_cents=amount_cents,
            paid_date=paid_date or date.today().isoformat(),
            description=description,
            notes=notes,
        )
        self.payments.insert(payment)
        return payment

    def get_payments(self, activity_id: str) -> list[ActivityPayment]:
        return self.payments.get_for_activity(activity_id)

    def get_cost_summary(self) -> dict[str, Any]:
        """Get cost summary by child and sport."""
        children = self.list_children()
        result: dict[str, Any] = {"children": [], "total_cents": 0}

        for child in children:
            activities = self.get_for_child(child.id)
            child_total = sum(a.cost_cents for a in activities)
            result["children"].append({
                "name": child.name,
                "id": child.id,
                "activities": [
                    {"name": a.name, "sport": a.sport_or_type, "cost_cents": a.cost_cents}
                    for a in activities
                ],
                "total_cents": child_total,
            })
            result["total_cents"] += child_total

        return result
