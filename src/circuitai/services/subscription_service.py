"""Subscription detection and management service."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ValidationError
from circuitai.models.subscription import Subscription, SubscriptionRepository

# Prefixes to strip from transaction descriptions (sorted longest-first for greedy matching)
_STRIP_PREFIXES = sorted(
    [
        "AUTOMATIC PAYMENT",
        "DEBIT CARD PURCHASE",
        "RECURRING PAYMENT",
        "ONLINE PURCHASE",
        "ONLINE PAYMENT",
        "BILL PAYMENT",
        "ACH PAYMENT",
        "ACH CREDIT",
        "ACH DEBIT",
        "POS DEBIT",
        "MASTERCARD",
        "VISA",
    ],
    key=len,
    reverse=True,
)

# Regex for trailing reference numbers and dates
_TRAILING_REF = re.compile(r"\s*\d{6,}$")
_TRAILING_DATE = re.compile(r"\s*\d{2}/\d{2}$")

# Frequency classification buckets (interval in days)
_FREQ_BUCKETS = {
    "weekly": (5, 9),
    "monthly": (25, 35),
    "quarterly": (80, 100),
    "yearly": (350, 380),
}

# Expected interval in days for each frequency
_FREQ_INTERVALS = {
    "weekly": 7,
    "monthly": 30,
    "quarterly": 90,
    "yearly": 365,
}


def normalize_vendor(description: str) -> str:
    """Normalize a transaction description to a vendor name.

    Strips payment method prefixes, trailing reference numbers/dates,
    and normalizes whitespace. Returns uppercase.
    """
    text = description.strip().upper()

    for prefix in _STRIP_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    # Strip trailing reference numbers and dates
    text = _TRAILING_REF.sub("", text)
    text = _TRAILING_DATE.sub("", text)

    # Normalize whitespace
    text = " ".join(text.split())
    return text


def _classify_frequency(intervals: list[int]) -> str | None:
    """Classify a list of day-intervals into a frequency bucket."""
    if not intervals:
        return None

    median = sorted(intervals)[len(intervals) // 2]

    for freq, (lo, hi) in _FREQ_BUCKETS.items():
        if lo <= median <= hi:
            return freq
    return None


def _score_confidence(
    count: int,
    intervals: list[int],
    amounts: list[int],
    frequency: str,
) -> int:
    """Score confidence 0-100 based on occurrence, interval consistency, and amount consistency."""
    # Occurrence score: min(count, 6) * 5 → max 30
    occurrence_score = min(count, 6) * 5

    # Interval consistency: what fraction of intervals fall in the expected bucket
    lo, hi = _FREQ_BUCKETS[frequency]
    in_range = sum(1 for iv in intervals if lo <= iv <= hi)
    interval_score = int((in_range / len(intervals)) * 40) if intervals else 0

    # Amount consistency: 30 if spread <= 10%, scaled down proportionally
    if amounts:
        avg = sum(amounts) / len(amounts)
        if avg > 0:
            max_spread = max(abs(a - avg) / avg for a in amounts)
            if max_spread <= 0.10:
                amount_score = 30
            else:
                amount_score = max(0, int(30 * (1 - (max_spread - 0.10) / 0.20)))
        else:
            amount_score = 0
    else:
        amount_score = 0

    return occurrence_score + interval_score + amount_score


class SubscriptionService:
    """Business logic for subscription detection and management."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.repo = SubscriptionRepository(db)

    def detect_subscriptions(self, months: int = 6) -> list[Subscription]:
        """Scan transactions and detect recurring charges.

        Returns unsaved Subscription objects sorted by confidence desc.
        """
        cutoff = (date.today() - timedelta(days=months * 30)).isoformat()

        # Gather debits from account transactions (negative = debit)
        acct_rows = self.db.fetchall(
            "SELECT description, amount_cents, transaction_date "
            "FROM account_transactions WHERE amount_cents < 0 AND transaction_date >= ?",
            (cutoff,),
        )

        # Gather charges from card transactions (positive = charge)
        card_rows = self.db.fetchall(
            "SELECT description, amount_cents, transaction_date "
            "FROM card_transactions WHERE amount_cents > 0 AND transaction_date >= ?",
            (cutoff,),
        )

        # Normalize and group by vendor
        vendor_txns: dict[str, list[dict[str, Any]]] = {}
        for row in acct_rows:
            vendor = normalize_vendor(row["description"])
            if not vendor:
                continue
            vendor_txns.setdefault(vendor, []).append({
                "amount_cents": abs(row["amount_cents"]),
                "date": row["transaction_date"],
            })
        for row in card_rows:
            vendor = normalize_vendor(row["description"])
            if not vendor:
                continue
            vendor_txns.setdefault(vendor, []).append({
                "amount_cents": abs(row["amount_cents"]),
                "date": row["transaction_date"],
            })

        # Exclude known patterns
        existing_patterns = self.repo.get_all_match_patterns()
        bill_patterns = self._get_bill_patterns()
        excluded = existing_patterns | bill_patterns

        results: list[Subscription] = []

        for vendor, txns in vendor_txns.items():
            if vendor in excluded:
                continue
            if len(txns) < 3:
                continue

            # Sort by date
            txns.sort(key=lambda t: t["date"])

            # Compute intervals
            dates = [date.fromisoformat(t["date"][:10]) for t in txns]
            intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]

            if not intervals:
                continue

            # Classify frequency
            frequency = _classify_frequency(intervals)
            if frequency is None:
                continue

            # Score confidence
            amounts = [t["amount_cents"] for t in txns]
            confidence = _score_confidence(len(txns), intervals, amounts, frequency)
            if confidence < 40:
                continue

            # Average amount
            avg_amount = int(sum(amounts) / len(amounts))

            # Predict next charge date
            expected_interval = _FREQ_INTERVALS[frequency]
            next_charge = (dates[-1] + timedelta(days=expected_interval)).isoformat()

            sub = Subscription(
                name=vendor.title(),
                provider=vendor.title(),
                amount_cents=avg_amount,
                frequency=frequency,
                status="active",
                next_charge_date=next_charge,
                last_charge_date=dates[-1].isoformat(),
                first_detected=date.today().isoformat(),
                confidence=confidence,
                match_pattern=vendor,
                source="detected",
            )
            results.append(sub)

        # Sort by confidence descending
        results.sort(key=lambda s: s.confidence, reverse=True)
        return results

    def _get_bill_patterns(self) -> set[str]:
        """Get normalized patterns from existing bills."""
        import json

        rows = self.db.fetchall(
            "SELECT match_patterns FROM bills WHERE is_active = 1",
        )
        patterns: set[str] = set()
        for row in rows:
            try:
                for p in json.loads(row["match_patterns"]):
                    patterns.add(p.upper())
            except (json.JSONDecodeError, TypeError):
                pass
        return patterns

    def confirm_detected(self, subscriptions: list[Subscription]) -> int:
        """Persist a list of detected subscriptions. Returns count saved."""
        count = 0
        for sub in subscriptions:
            # Skip if already exists (idempotent)
            existing = self.repo.find_by_match_pattern(sub.match_pattern)
            if existing:
                continue
            self.repo.insert(sub)
            count += 1
        return count

    def add_subscription(
        self,
        name: str,
        amount_cents: int = 0,
        frequency: str = "monthly",
        category: str = "other",
        notes: str = "",
    ) -> Subscription:
        """Manually add a subscription."""
        if not name:
            raise ValidationError("Subscription name is required.")
        if amount_cents < 0:
            raise ValidationError("Amount cannot be negative.")
        if frequency not in ("weekly", "monthly", "quarterly", "yearly"):
            raise ValidationError(f"Invalid frequency: {frequency}")

        sub = Subscription(
            name=name,
            provider=name,
            amount_cents=amount_cents,
            frequency=frequency,
            category=category,
            status="active",
            source="manual",
            match_pattern=name.upper(),
            first_detected=date.today().isoformat(),
            notes=notes,
        )
        self.repo.insert(sub)
        return sub

    def list_subscriptions(self, active_only: bool = True) -> list[Subscription]:
        return self.repo.list_all(active_only=active_only)  # type: ignore[return-value]

    def get_subscription(self, sub_id: str) -> Subscription:
        return self.repo.get(sub_id)  # type: ignore[return-value]

    def update_subscription(self, sub_id: str, **updates: Any) -> Subscription:
        return self.repo.update(sub_id, **updates)  # type: ignore[return-value]

    def cancel_subscription(self, sub_id: str) -> Subscription:
        """Mark a subscription as cancelled."""
        return self.repo.update(sub_id, status="cancelled")  # type: ignore[return-value]

    def get_upcoming(self, within_days: int = 7) -> list[Subscription]:
        return self.repo.get_upcoming(within_days=within_days)

    def get_summary(self) -> dict[str, Any]:
        """Get subscription cost summary."""
        subs = self.list_subscriptions()
        active = [s for s in subs if s.status == "active"]

        monthly_total = sum(s.monthly_cost_cents for s in active)
        yearly_total = sum(s.yearly_cost_cents for s in active)

        by_category: dict[str, int] = {}
        for s in active:
            by_category[s.category] = by_category.get(s.category, 0) + s.monthly_cost_cents

        by_frequency: dict[str, int] = {}
        for s in active:
            by_frequency[s.frequency] = by_frequency.get(s.frequency, 0) + 1

        upcoming = self.get_upcoming(within_days=7)

        return {
            "total_active": len(active),
            "monthly_total_cents": monthly_total,
            "yearly_total_cents": yearly_total,
            "by_category": by_category,
            "by_frequency": by_frequency,
            "upcoming_count": len(upcoming),
        }
