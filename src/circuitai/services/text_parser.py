"""Free-form text parser — converts natural language to structured entries."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import ParseError

# Amount patterns: $142, $142.30, 142 dollars
_AMOUNT_RE = re.compile(r"\$\s*([\d,]+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*dollars?", re.IGNORECASE)

# Date patterns
_DATE_PATTERNS = [
    (re.compile(
        r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|"
        r"sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
        re.IGNORECASE,
    ), "month_day"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b"), "slash"),
    (re.compile(r"\btomorrow\b", re.IGNORECASE), "tomorrow"),
    (re.compile(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE), "next_day"),
    (re.compile(r"\bon the (\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE), "on_day"),
]

# Recurrence keywords
_RECURRENCE_RE = re.compile(r"\b(monthly|quarterly|yearly|annually|weekly|biweekly|semi-annual)\b", re.IGNORECASE)

# Entity type keywords
_BILL_KEYWORDS = {"bill", "utility", "electric", "water", "gas", "internet", "insurance", "subscription", "hoa", "tax"}
_PAYMENT_KEYWORDS = {"paid", "pay", "payment", "settled"}
_DEADLINE_KEYWORDS = {"deadline", "due", "appointment", "dentist", "doctor", "meeting"}
_ACTIVITY_KEYWORDS = {
    "practice", "game", "lesson", "class", "registration", "tournament",
    "hockey", "soccer", "gymnastics", "tennis", "baseball", "basketball", "swimming",
}

_MONTH_MAP = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6,
    "jul": 7, "july": 7, "aug": 8, "august": 8, "sep": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


class TextParser:
    """Parses free-form text into structured entries."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db

    def parse(self, text: str) -> dict[str, Any]:
        """Parse text into a structured dict with entity_type, fields, and confidence."""
        text = text.strip()
        result: dict[str, Any] = {
            "raw_text": text,
            "entity_type": None,
            "fields": {},
            "confidence": 0.0,
        }

        # Extract amount
        amount = self._extract_amount(text)
        if amount is not None:
            result["fields"]["amount_cents"] = amount
            result["confidence"] += 0.2

        # Extract date
        parsed_date = self._extract_date(text)
        if parsed_date:
            result["fields"]["date"] = parsed_date
            result["confidence"] += 0.1

        # Extract recurrence
        recurrence = self._extract_recurrence(text)
        if recurrence:
            result["fields"]["frequency"] = recurrence

        # Determine entity type
        text_lower = text.lower()
        words = set(text_lower.split())

        if words & _PAYMENT_KEYWORDS:
            result["entity_type"] = "payment"
            result["confidence"] += 0.3
        elif words & _ACTIVITY_KEYWORDS:
            result["entity_type"] = "activity"
            result["confidence"] += 0.3
            # Check for child name
            child_name = self._find_child_name(text)
            if child_name:
                result["fields"]["child_name"] = child_name
                result["confidence"] += 0.1
        elif words & _BILL_KEYWORDS or (amount and parsed_date):
            result["entity_type"] = "bill"
            result["confidence"] += 0.3
        elif words & _DEADLINE_KEYWORDS:
            result["entity_type"] = "deadline"
            result["confidence"] += 0.3
        elif amount:
            result["entity_type"] = "bill"  # default if there's money involved
            result["confidence"] += 0.1

        # Extract the name/description (remove extracted parts)
        name = self._extract_name(text)
        if name:
            result["fields"]["name"] = name
            result["confidence"] += 0.1

        # Try to match against existing entities
        match = self._match_existing(text)
        if match:
            result["matched_entity"] = match
            result["confidence"] += 0.2

        return result

    def describe(self, parsed: dict[str, Any]) -> str:
        """Describe what would be created from the parsed result."""
        fields = parsed.get("fields", {})
        entity = parsed.get("entity_type", "entry")
        name = fields.get("name", "Unknown")
        parts = [f"Add {entity}: {name}"]

        if "amount_cents" in fields:
            from circuitai.output.formatter import dollars
            parts.append(dollars(fields["amount_cents"]))

        if "date" in fields:
            parts.append(f"due {fields['date']}")

        if "child_name" in fields:
            parts.append(f"for {fields['child_name']}")

        return ", ".join(parts)

    def execute(self, parsed: dict[str, Any]) -> str:
        """Execute the parsed action — create the entity."""
        entity_type = parsed.get("entity_type")
        fields = parsed.get("fields", {})

        if entity_type == "bill":
            return self._create_bill(fields)
        elif entity_type == "payment":
            return self._record_payment(fields, parsed.get("raw_text", ""))
        elif entity_type == "activity":
            return self._create_activity(fields)
        elif entity_type == "deadline":
            return self._create_deadline(fields)
        else:
            raise ParseError(f"Don't know how to create a '{entity_type}'.")

    def parse_and_execute(self, text: str) -> str:
        """Parse and execute in one step (for action keywords like 'paid')."""
        parsed = self.parse(text)
        if parsed["confidence"] < 0.3:
            raise ParseError(f"Couldn't understand: {text}")
        return self.execute(parsed)

    # ── Extractors ───────────────────────────────────────────

    def _extract_amount(self, text: str) -> int | None:
        match = _AMOUNT_RE.search(text)
        if match:
            amount_str = (match.group(1) or match.group(2)).replace(",", "")
            return int(float(amount_str) * 100)
        return None

    def _extract_date(self, text: str) -> str | None:
        today = date.today()

        for pattern, kind in _DATE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue

            if kind == "month_day":
                month_str = match.group(1).lower()[:3]
                day = int(match.group(2))
                year = int(match.group(3)) if match.group(3) else today.year
                month = _MONTH_MAP.get(month_str, 1)
                try:
                    d = date(year, month, day)
                    if d < today and not match.group(3):
                        d = d.replace(year=today.year + 1)
                    return d.isoformat()
                except ValueError:
                    continue

            elif kind == "slash":
                month = int(match.group(1))
                day = int(match.group(2))
                year = int(match.group(3)) if match.group(3) else today.year
                if year < 100:
                    year += 2000
                try:
                    return date(year, month, day).isoformat()
                except ValueError:
                    continue

            elif kind == "tomorrow":
                return (today + timedelta(days=1)).isoformat()

            elif kind == "next_day":
                day_name = match.group(1).lower()
                days = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
                target = days.index(day_name)
                current = today.weekday()
                diff = (target - current) % 7
                if diff == 0:
                    diff = 7
                return (today + timedelta(days=diff)).isoformat()

            elif kind == "on_day":
                day = int(match.group(1))
                try:
                    d = today.replace(day=day)
                    if d <= today:
                        if today.month == 12:
                            d = d.replace(year=today.year + 1, month=1)
                        else:
                            d = d.replace(month=today.month + 1)
                    return d.isoformat()
                except ValueError:
                    continue

        return None

    def _extract_recurrence(self, text: str) -> str | None:
        match = _RECURRENCE_RE.search(text)
        if match:
            freq = match.group(1).lower()
            if freq == "annually":
                freq = "yearly"
            return freq
        return None

    def _extract_name(self, text: str) -> str:
        """Extract the entity name by removing extracted parts."""
        cleaned = text
        # Remove amounts
        cleaned = _AMOUNT_RE.sub("", cleaned)
        # Remove date-like parts
        for pattern, _ in _DATE_PATTERNS:
            cleaned = pattern.sub("", cleaned)
        # Remove recurrence keywords
        cleaned = _RECURRENCE_RE.sub("", cleaned)
        # Remove common keywords
        for kw in _BILL_KEYWORDS | _PAYMENT_KEYWORDS | _DEADLINE_KEYWORDS | {"for", "due", "on"}:
            cleaned = re.sub(rf"\b{kw}\b", "", cleaned, flags=re.IGNORECASE)
        # Clean up whitespace
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    def _find_child_name(self, text: str) -> str | None:
        """Try to match a child name in the text."""
        try:
            from circuitai.models.activity import ChildRepository
            children = ChildRepository(self.db).list_all()
            text_lower = text.lower()
            for child in children:
                if child.name.lower() in text_lower:
                    return child.name
        except Exception:
            pass

        # Check for "for <Name>" pattern
        match = re.search(r"\bfor\s+([A-Z][a-z]+)\b", text)
        if match:
            return match.group(1)
        return None

    def _match_existing(self, text: str) -> dict[str, str] | None:
        """Try to match text against existing bills, activities, etc."""
        text_lower = text.lower()
        try:
            from circuitai.models.bill import BillRepository
            for bill in BillRepository(self.db).list_all():
                if bill.name.lower() in text_lower or bill.provider.lower() in text_lower:
                    return {"type": "bill", "id": bill.id, "name": bill.name}
        except Exception:
            pass
        return None

    # ── Creators ─────────────────────────────────────────────

    def _create_bill(self, fields: dict[str, Any]) -> str:
        from circuitai.services.bill_service import BillService
        svc = BillService(self.db)
        due_day = None
        if "date" in fields:
            try:
                due_day = int(fields["date"].split("-")[2])
            except (ValueError, IndexError):
                pass

        bill = svc.add_bill(
            name=fields.get("name", "New Bill"),
            amount_cents=fields.get("amount_cents", 0),
            due_day=due_day,
            frequency=fields.get("frequency", "monthly"),
        )
        from circuitai.output.formatter import dollars
        return f"Added bill: {bill.name}, {dollars(bill.amount_cents)}, due day {bill.due_day}"

    def _record_payment(self, fields: dict[str, Any], raw_text: str) -> str:
        match = self._match_existing(raw_text)
        if match and match["type"] == "bill":
            from circuitai.services.bill_service import BillService
            svc = BillService(self.db)
            payment = svc.pay_bill(
                bill_id=match["id"],
                amount_cents=fields.get("amount_cents"),
                paid_date=fields.get("date"),
            )
            from circuitai.output.formatter import dollars
            return f"Recorded payment of {dollars(payment.amount_cents)} for {match['name']}"
        return "Recorded payment (no matching bill found — added as note)"

    def _create_activity(self, fields: dict[str, Any]) -> str:
        from circuitai.services.activity_service import ActivityService
        svc = ActivityService(self.db)

        child_id = None
        if "child_name" in fields:
            child = svc.find_child(fields["child_name"])
            if child:
                child_id = child.id

        activity = svc.add_activity(
            name=fields.get("name", "New Activity"),
            child_id=child_id,
            cost_cents=fields.get("amount_cents", 0),
        )
        return f"Added activity: {activity.name}"

    def _create_deadline(self, fields: dict[str, Any]) -> str:
        from circuitai.services.deadline_service import DeadlineService
        svc = DeadlineService(self.db)
        dl = svc.add_deadline(
            title=fields.get("name", "New Deadline"),
            due_date=fields.get("date", date.today().isoformat()),
        )
        return f"Added deadline: {dl.title}, due {dl.due_date}"
