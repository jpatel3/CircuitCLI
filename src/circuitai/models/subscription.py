"""Subscription model and repository."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from circuitai.models.base import BaseRepository, CircuitModel


class Subscription(CircuitModel):
    """A recurring subscription detected from transactions or added manually."""

    name: str
    provider: str = ""
    amount_cents: int = 0
    frequency: str = "monthly"  # weekly, monthly, quarterly, yearly
    category: str = "other"
    status: str = "active"  # active, paused, cancelled
    next_charge_date: str | None = None
    last_charge_date: str | None = None
    first_detected: str | None = None
    confidence: int = 0  # 0-100
    match_pattern: str = ""  # normalized vendor string, idempotency key
    source: str = "detected"  # detected, manual
    linked_bill_id: str | None = None
    notes: str = ""
    is_active: bool = True

    @property
    def confidence_score(self) -> float:
        """Confidence as a 0.0-1.0 float."""
        return self.confidence / 100

    @property
    def amount_dollars(self) -> float:
        return self.amount_cents / 100

    @property
    def monthly_cost_cents(self) -> int:
        """Normalize cost to monthly."""
        if self.frequency == "weekly":
            return int(self.amount_cents * 52 / 12)
        elif self.frequency == "quarterly":
            return self.amount_cents // 3
        elif self.frequency == "yearly":
            return self.amount_cents // 12
        return self.amount_cents  # monthly

    @property
    def yearly_cost_cents(self) -> int:
        """Normalize cost to yearly."""
        if self.frequency == "weekly":
            return self.amount_cents * 52
        elif self.frequency == "monthly":
            return self.amount_cents * 12
        elif self.frequency == "quarterly":
            return self.amount_cents * 4
        return self.amount_cents  # yearly

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Subscription":
        d = {k: row[k] for k in row.keys()}
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class SubscriptionRepository(BaseRepository):
    table: ClassVar[str] = "subscriptions"
    model_class: ClassVar[type[CircuitModel]] = Subscription  # type: ignore[assignment]

    def find_by_match_pattern(self, pattern: str) -> Subscription | None:
        """Find a subscription by its normalized vendor pattern (idempotency)."""
        row = self.db.fetchone(
            "SELECT * FROM subscriptions WHERE match_pattern = ? AND is_active = 1",
            (pattern,),
        )
        return Subscription.from_row(row) if row else None

    def find_by_status(self, status: str) -> list[Subscription]:
        """Get subscriptions by status (active, paused, cancelled)."""
        rows = self.db.fetchall(
            "SELECT * FROM subscriptions WHERE status = ? AND is_active = 1 ORDER BY name",
            (status,),
        )
        return [Subscription.from_row(r) for r in rows]

    def get_upcoming(self, within_days: int = 7) -> list[Subscription]:
        """Get active subscriptions with next_charge_date within N days."""
        from datetime import date, timedelta

        today = date.today()
        cutoff = (today + timedelta(days=within_days)).isoformat()
        rows = self.db.fetchall(
            "SELECT * FROM subscriptions WHERE is_active = 1 AND status = 'active' "
            "AND next_charge_date IS NOT NULL AND next_charge_date <= ? "
            "AND next_charge_date >= ? ORDER BY next_charge_date",
            (cutoff, today.isoformat()),
        )
        return [Subscription.from_row(r) for r in rows]

    def get_all_match_patterns(self) -> set[str]:
        """Get all match_pattern values for fast exclusion during detection."""
        rows = self.db.fetchall(
            "SELECT match_pattern FROM subscriptions WHERE is_active = 1",
        )
        return {r["match_pattern"] for r in rows if r["match_pattern"]}
