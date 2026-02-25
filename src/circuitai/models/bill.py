"""Bill and BillPayment models and repositories."""

from __future__ import annotations

import json
from typing import Any, ClassVar

from pydantic import Field

from circuitai.core.database import DatabaseConnection
from circuitai.models.base import BaseRepository, CircuitModel, new_id, now_iso


class Bill(CircuitModel):
    """A recurring bill (utility, insurance, subscription, etc.)."""

    name: str
    provider: str = ""
    category: str = "other"
    amount_cents: int = 0
    due_day: int | None = None
    frequency: str = "monthly"  # monthly, quarterly, yearly, one-time
    account_id: str | None = None
    auto_pay: bool = False
    match_patterns: str = "[]"  # JSON array of description patterns
    notes: str = ""
    is_active: bool = True

    @property
    def amount_dollars(self) -> float:
        return self.amount_cents / 100

    @property
    def patterns(self) -> list[str]:
        return json.loads(self.match_patterns)

    def add_pattern(self, pattern: str) -> None:
        patterns = self.patterns
        if pattern not in patterns:
            patterns.append(pattern)
            self.match_patterns = json.dumps(patterns)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["auto_pay"] = int(data["auto_pay"])
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "Bill":
        d = {k: row[k] for k in row.keys()}
        d["auto_pay"] = bool(d.get("auto_pay", 0))
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class BillPayment(CircuitModel):
    """A payment made against a bill."""

    bill_id: str
    amount_cents: int
    paid_date: str
    payment_method: str = ""
    confirmation: str = ""
    notes: str = ""
    updated_at: str = Field(default="", exclude=True)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "BillPayment":
        d = {k: row[k] for k in row.keys()}
        d.pop("updated_at", None)
        return cls(**d)


class BillRepository(BaseRepository):
    table: ClassVar[str] = "bills"
    model_class: ClassVar[type[CircuitModel]] = Bill  # type: ignore[assignment]

    def find_by_name(self, name: str) -> list[Bill]:
        """Search bills by name (case-insensitive partial match)."""
        rows = self.db.fetchall(
            "SELECT * FROM bills WHERE LOWER(name) LIKE ? AND is_active = 1",
            (f"%{name.lower()}%",),
        )
        return [Bill.from_row(r) for r in rows]

    def get_due_soon(self, within_days: int = 7) -> list[Bill]:
        """Get active bills due within N days (based on due_day of current month)."""
        from datetime import date, timedelta
        today = date.today()
        rows = self.db.fetchall(
            "SELECT * FROM bills WHERE is_active = 1 AND due_day IS NOT NULL ORDER BY due_day",
        )
        result = []
        for row in rows:
            bill = Bill.from_row(row)
            if bill.due_day:
                try:
                    due = today.replace(day=bill.due_day)
                except ValueError:
                    # Day doesn't exist in this month (e.g., 31st in Feb)
                    import calendar
                    last_day = calendar.monthrange(today.year, today.month)[1]
                    due = today.replace(day=min(bill.due_day, last_day))

                if due < today:
                    # Due date already passed this month; check next month
                    if today.month == 12:
                        due = due.replace(year=today.year + 1, month=1)
                    else:
                        due = due.replace(month=today.month + 1)

                diff = (due - today).days
                if 0 <= diff <= within_days:
                    result.append(bill)
        return result


class BillPaymentRepository(BaseRepository):
    table: ClassVar[str] = "bill_payments"
    model_class: ClassVar[type[CircuitModel]] = BillPayment  # type: ignore[assignment]

    def get_for_bill(self, bill_id: str, limit: int = 10) -> list[BillPayment]:
        """Get recent payments for a specific bill."""
        rows = self.db.fetchall(
            "SELECT * FROM bill_payments WHERE bill_id = ? ORDER BY paid_date DESC LIMIT ?",
            (bill_id, limit),
        )
        return [BillPayment.from_row(r) for r in rows]

    def get_last_payment(self, bill_id: str) -> BillPayment | None:
        """Get the most recent payment for a bill."""
        row = self.db.fetchone(
            "SELECT * FROM bill_payments WHERE bill_id = ? ORDER BY paid_date DESC LIMIT 1",
            (bill_id,),
        )
        return BillPayment.from_row(row) if row else None

    def total_paid(self, bill_id: str) -> int:
        """Total amount paid for a bill (in cents)."""
        row = self.db.fetchone(
            "SELECT COALESCE(SUM(amount_cents), 0) as total FROM bill_payments WHERE bill_id = ?",
            (bill_id,),
        )
        return row["total"] if row else 0
