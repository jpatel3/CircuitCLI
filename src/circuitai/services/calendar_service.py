"""CalDAV two-way sync engine for calendar integration."""

from __future__ import annotations

import calendar as cal_mod
import json
from datetime import date, datetime, timedelta
from typing import Any

from circuitai.core.config import load_config
from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import CalendarSyncError
from circuitai.models.base import now_iso

# CalDAV is optional
try:
    import caldav  # type: ignore[import-untyped]

    HAS_CALDAV = True
except ImportError:
    HAS_CALDAV = False


def _build_vevent(
    uid: str,
    summary: str,
    dtstart: date,
    description: str = "",
    all_day: bool = True,
    alarm_minutes: int = 1440,
) -> str:
    """Build a VCALENDAR string for an event."""
    now = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    dtstart_str = dtstart.strftime("%Y%m%d")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//CircuitAI//EN",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"DTSTART;VALUE=DATE:{dtstart_str}",
        f"SUMMARY:{summary}",
    ]

    if description:
        # Escape newlines in description
        desc = description.replace("\n", "\\n")
        lines.append(f"DESCRIPTION:{desc}")

    if alarm_minutes > 0:
        lines.extend([
            "BEGIN:VALARM",
            "TRIGGER:-PT" + str(alarm_minutes) + "M",
            "ACTION:DISPLAY",
            f"DESCRIPTION:Reminder: {summary}",
            "END:VALARM",
        ])

    lines.extend([
        "END:VEVENT",
        "END:VCALENDAR",
    ])
    return "\r\n".join(lines)


class CalendarService:
    """Manages two-way CalDAV sync for bills, deadlines, and activities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.config = load_config().get("calendar", {})
        self._client = None
        self._calendar = None

    @property
    def is_configured(self) -> bool:
        return bool(self.config.get("enabled")) and bool(self.config.get("server_url"))

    def get_status(self) -> dict[str, Any]:
        """Get calendar sync status."""
        if not HAS_CALDAV:
            return {"status": "unavailable", "reason": "caldav package not installed"}
        if not self.is_configured:
            return {
                "status": "not_configured",
                "reason": "Calendar not configured. Run 'circuit calendar setup'.",
            }

        row = self.db.fetchone(
            "SELECT MAX(last_synced_at) as last_sync FROM calendar_sync_log"
        )
        last_sync = row["last_sync"] if row and row["last_sync"] else None

        count = self.db.fetchone("SELECT COUNT(*) as cnt FROM calendar_sync_log")
        synced_count = count["cnt"] if count else 0

        return {
            "status": "configured",
            "server_url": self.config.get("server_url", ""),
            "calendar_name": self.config.get("calendar_name", "CircuitAI"),
            "last_sync": last_sync,
            "synced_items": synced_count,
            "sync_bills": self.config.get("sync_bills", True),
            "sync_deadlines": self.config.get("sync_deadlines", True),
            "sync_activities": self.config.get("sync_activities", True),
        }

    def connect(self) -> Any:
        """Connect to the CalDAV server and find/create the target calendar."""
        if not HAS_CALDAV:
            raise CalendarSyncError(
                "caldav package not installed. Install with: pip install circuitai[calendar]"
            )
        if not self.is_configured:
            raise CalendarSyncError("Calendar not configured. Run 'circuit calendar setup'.")

        creds = self.db.fetchone(
            "SELECT value FROM adapter_state "
            "WHERE adapter_name = 'calendar' AND key = 'credentials'"
        )
        if not creds:
            raise CalendarSyncError("Calendar credentials not found. Run 'circuit calendar setup'.")

        cred_data = json.loads(creds["value"])

        try:
            self._client = caldav.DAVClient(
                url=self.config["server_url"],
                username=cred_data.get("username", ""),
                password=cred_data.get("password", ""),
            )
            principal = self._client.principal()
            cal_name = self.config.get("calendar_name", "CircuitAI")

            # Find or create the target calendar
            for cal in principal.calendars():
                if cal.name == cal_name:
                    self._calendar = cal
                    return self._client

            # Calendar not found — try to create it
            self._calendar = principal.make_calendar(name=cal_name)
            return self._client
        except Exception as e:
            raise CalendarSyncError(f"Failed to connect to CalDAV server: {e}") from e

    def sync(self) -> dict[str, Any]:
        """Run a full sync cycle: push local changes then pull remote changes."""
        if not self.is_configured:
            return {"status": "skipped", "reason": "not configured"}

        results: dict[str, Any] = {"pushed": 0, "pulled": 0, "errors": []}

        try:
            self.connect()

            if self.config.get("sync_bills", True):
                r = self._push_bills()
                results["pushed"] += r.get("pushed", 0)

            if self.config.get("sync_deadlines", True):
                r = self._push_deadlines()
                results["pushed"] += r.get("pushed", 0)

            if self.config.get("sync_activities", True):
                r = self._push_activities()
                results["pushed"] += r.get("pushed", 0)

            # Pull changes from calendar
            r = self._pull_changes()
            results["pulled"] += r.get("pulled", 0)

        except CalendarSyncError as e:
            results["errors"].append(str(e))
        except Exception as e:
            results["errors"].append(f"Sync failed: {e}")

        results["status"] = "error" if results["errors"] else "success"
        return results

    def _get_or_create_uid(self, entity_type: str, entity_id: str) -> str:
        """Get or create a stable calendar UID for an entity."""
        row = self.db.fetchone(
            "SELECT calendar_uid FROM calendar_sync_log "
            "WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        )
        if row:
            return row["calendar_uid"]

        uid = f"circuitai-{entity_type}-{entity_id}@circuit.local"
        return uid

    def _record_sync(
        self, entity_type: str, entity_id: str, calendar_uid: str
    ) -> None:
        """Record a sync event in the log."""
        self.db.execute(
            """INSERT OR REPLACE INTO calendar_sync_log
               (entity_type, entity_id, calendar_uid, last_synced_at, sync_direction)
               VALUES (?, ?, ?, ?, 'push')""",
            (entity_type, entity_id, calendar_uid, now_iso()),
        )
        self.db.commit()

    def _push_event(
        self,
        entity_type: str,
        entity_id: str,
        summary: str,
        event_date: date,
        description: str = "",
    ) -> bool:
        """Push a single event to the calendar."""
        if not self._calendar:
            return False

        uid = self._get_or_create_uid(entity_type, entity_id)
        vcal = _build_vevent(
            uid=uid,
            summary=summary,
            dtstart=event_date,
            description=description,
        )

        try:
            self._calendar.save_event(vcal)
            self._record_sync(entity_type, entity_id, uid)
            return True
        except Exception:
            return False

    def _push_bills(self) -> dict[str, int]:
        """Push bill due dates to calendar as all-day events."""
        from circuitai.services.bill_service import BillService

        svc = BillService(self.db)
        bills = svc.list_bills()
        pushed = 0

        today = date.today()
        for bill in bills:
            if not bill.due_day:
                continue

            # Calculate next due date
            last_day = cal_mod.monthrange(today.year, today.month)[1]
            due = today.replace(day=min(bill.due_day, last_day))
            if due < today:
                if today.month == 12:
                    due = date(today.year + 1, 1, min(bill.due_day, 31))
                else:
                    nl = cal_mod.monthrange(today.year, today.month + 1)[1]
                    due = date(today.year, today.month + 1, min(bill.due_day, nl))

            desc = f"Amount: ${bill.amount_cents / 100:.2f}\nProvider: {bill.provider}"
            if self._push_event("bill", bill.id, f"Bill Due: {bill.name}", due, desc):
                pushed += 1

        return {"pushed": pushed}

    def _push_deadlines(self) -> dict[str, int]:
        """Push deadlines to calendar."""
        from circuitai.services.deadline_service import DeadlineService

        svc = DeadlineService(self.db)
        deadlines = svc.list_deadlines()
        pushed = 0

        for dl in deadlines:
            if not dl.due_date:
                continue
            try:
                due = date.fromisoformat(dl.due_date[:10])
            except ValueError:
                continue

            prio = f" [{dl.priority.upper()}]" if dl.priority != "medium" else ""
            desc = dl.description or ""
            if self._push_event(
                "deadline", dl.id, f"Deadline{prio}: {dl.title}", due, desc
            ):
                pushed += 1

        return {"pushed": pushed}

    def _push_activities(self) -> dict[str, int]:
        """Push activity schedules to calendar."""
        from circuitai.services.activity_service import ActivityService

        svc = ActivityService(self.db)
        activities = svc.list_activities()
        pushed = 0

        for act in activities:
            if not act.schedule:
                continue

            # For activities, push as a recurring note on next occurrence
            today = date.today()
            desc = f"Schedule: {act.schedule}"
            if act.location:
                desc += f"\nLocation: {act.location}"

            if self._push_event(
                "activity", act.id, f"Activity: {act.name}", today, desc
            ):
                pushed += 1

        return {"pushed": pushed}

    def _pull_changes(self) -> dict[str, int]:
        """Pull changes from calendar (detect rescheduled events)."""
        if not self._calendar:
            return {"pulled": 0}

        pulled = 0
        try:
            # Fetch events for the next 30 days
            start = date.today()
            end = start + timedelta(days=30)
            events = self._calendar.date_search(
                start=start, end=end, expand=True
            )

            for event in events:
                try:
                    vevent = event.vobject_instance.vevent
                    uid = str(vevent.uid.value)

                    # Check if this is one of our events
                    row = self.db.fetchone(
                        "SELECT entity_type, entity_id FROM calendar_sync_log "
                        "WHERE calendar_uid = ?",
                        (uid,),
                    )
                    if not row:
                        continue

                    # Check if the date changed
                    new_date = vevent.dtstart.value
                    if isinstance(new_date, datetime):
                        new_date = new_date.date()
                    new_date_str = new_date.isoformat()

                    entity_type = row["entity_type"]
                    entity_id = row["entity_id"]

                    if entity_type == "deadline":
                        # Update deadline due_date if changed
                        dl = self.db.fetchone(
                            "SELECT due_date FROM deadlines WHERE id = ?",
                            (entity_id,),
                        )
                        if dl and dl["due_date"][:10] != new_date_str:
                            self.db.execute(
                                "UPDATE deadlines SET due_date = ? WHERE id = ?",
                                (new_date_str, entity_id),
                            )
                            self.db.commit()
                            pulled += 1

                except Exception:
                    continue

        except Exception:
            pass

        return {"pulled": pulled}
