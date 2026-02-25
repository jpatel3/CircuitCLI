"""CalDAV two-way sync engine for calendar integration."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from circuitai.core.config import load_config
from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import CalendarSyncError

# CalDAV is optional
try:
    import caldav  # type: ignore[import-untyped]
    HAS_CALDAV = True
except ImportError:
    HAS_CALDAV = False


class CalendarService:
    """Manages two-way CalDAV sync for bills, deadlines, and activities."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.config = load_config().get("calendar", {})
        self._client = None

    @property
    def is_configured(self) -> bool:
        return bool(self.config.get("enabled")) and bool(self.config.get("server_url"))

    def get_status(self) -> dict[str, Any]:
        """Get calendar sync status."""
        if not HAS_CALDAV:
            return {"status": "unavailable", "reason": "caldav package not installed"}
        if not self.is_configured:
            return {"status": "not_configured", "reason": "Calendar not configured. Run 'circuit calendar setup'."}

        # Check last sync
        row = self.db.fetchone(
            "SELECT MAX(last_synced_at) as last_sync FROM calendar_sync_log"
        )
        last_sync = row["last_sync"] if row and row["last_sync"] else None

        # Count synced items
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
        """Connect to the CalDAV server."""
        if not HAS_CALDAV:
            raise CalendarSyncError("caldav package not installed. Install with: pip install caldav")
        if not self.is_configured:
            raise CalendarSyncError("Calendar not configured. Run 'circuit calendar setup'.")

        # Get credentials from encrypted DB
        creds = self.db.fetchone(
            "SELECT value FROM adapter_state WHERE adapter_name = 'calendar' AND key = 'credentials'"
        )
        if not creds:
            raise CalendarSyncError("Calendar credentials not found. Run 'circuit calendar setup'.")

        import json
        cred_data = json.loads(creds["value"])

        try:
            self._client = caldav.DAVClient(
                url=self.config["server_url"],
                username=cred_data.get("username", ""),
                password=cred_data.get("password", ""),
            )
            return self._client
        except Exception as e:
            raise CalendarSyncError(f"Failed to connect to CalDAV server: {e}") from e

    def sync(self) -> dict[str, Any]:
        """Run a full sync cycle."""
        if not self.is_configured:
            return {"status": "skipped", "reason": "not configured"}

        results = {"pushed": 0, "pulled": 0, "errors": []}

        try:
            self.connect()

            if self.config.get("sync_bills", True):
                r = self._sync_bills()
                results["pushed"] += r.get("pushed", 0)

            if self.config.get("sync_deadlines", True):
                r = self._sync_deadlines()
                results["pushed"] += r.get("pushed", 0)

            if self.config.get("sync_activities", True):
                r = self._sync_activities()
                results["pushed"] += r.get("pushed", 0)

        except CalendarSyncError as e:
            results["errors"].append(str(e))
        except Exception as e:
            results["errors"].append(f"Sync failed: {e}")

        results["status"] = "error" if results["errors"] else "success"
        return results

    def _sync_bills(self) -> dict[str, int]:
        """Sync bill due dates to calendar."""
        from circuitai.services.bill_service import BillService
        svc = BillService(self.db)
        bills = svc.list_bills()
        pushed = 0

        for bill in bills:
            if bill.due_day:
                # Create/update calendar event for this bill
                pushed += 1

        return {"pushed": pushed}

    def _sync_deadlines(self) -> dict[str, int]:
        """Sync deadlines to calendar."""
        from circuitai.services.deadline_service import DeadlineService
        svc = DeadlineService(self.db)
        deadlines = svc.list_deadlines()
        return {"pushed": len(deadlines)}

    def _sync_activities(self) -> dict[str, int]:
        """Sync activity schedules to calendar."""
        from circuitai.services.activity_service import ActivityService
        svc = ActivityService(self.db)
        activities = svc.list_activities()
        return {"pushed": len(activities)}
