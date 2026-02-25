"""Unified integration registry — adapters + built-in services."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

from circuitai.core.database import DatabaseConnection


class IntegrationStatus(str, Enum):
    """Status of an integration."""

    available = "available"
    unavailable = "unavailable"
    configured = "configured"
    active = "active"
    error = "error"


@dataclass
class IntegrationInfo:
    """Describes a single integration (adapter or built-in service)."""

    name: str
    kind: str  # "adapter" or "builtin"
    description: str
    version: str = "0.1.0"
    status: IntegrationStatus = IntegrationStatus.available
    status_detail: str = ""
    requires: list[str] = field(default_factory=list)
    config_command: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["status"] = self.status.value
        return d


class IntegrationRegistry:
    """Combines adapter plugins and built-in services into a single registry."""

    def __init__(self, db: DatabaseConnection | None = None) -> None:
        self.db = db

    def list_all(self) -> list[IntegrationInfo]:
        """Return all integrations with current status."""
        return self._get_adapter_integrations() + self._get_builtin_integrations()

    def get(self, name: str) -> IntegrationInfo | None:
        """Look up a single integration by name."""
        for info in self.list_all():
            if info.name == name:
                return info
        return None

    def _get_adapter_integrations(self) -> list[IntegrationInfo]:
        """Query AdapterRegistry for installed adapter plugins."""
        from circuitai.adapters.registry import AdapterRegistry

        registry = AdapterRegistry()
        result = []
        for adapter in registry.list_adapters():
            result.append(IntegrationInfo(
                name=adapter["name"],
                kind="adapter",
                description=adapter.get("description", ""),
                version=adapter.get("version", "0.0.0"),
                status=IntegrationStatus.active,
                status_detail="Installed via entry_points",
                config_command=f"circuit adapters configure {adapter['name']}",
            ))
        return result

    def _get_builtin_integrations(self) -> list[IntegrationInfo]:
        """Check status of built-in services."""
        return [
            self._check_calendar(),
            self._check_statement_linker(),
            self._check_text_parser(),
            self._check_query_engine(),
        ]

    def _check_calendar(self) -> IntegrationInfo:
        """Check CalDAV calendar sync status."""
        from circuitai.services.calendar_service import HAS_CALDAV

        if not HAS_CALDAV:
            return IntegrationInfo(
                name="calendar-sync",
                kind="builtin",
                description="Two-way CalDAV calendar sync for bills, deadlines, and activities",
                status=IntegrationStatus.unavailable,
                status_detail="caldav package not installed",
                requires=["caldav"],
                config_command="circuit calendar setup",
            )

        if self.db is not None:
            from circuitai.services.calendar_service import CalendarService

            svc = CalendarService(self.db)
            cal_status = svc.get_status()
            if cal_status["status"] == "configured":
                return IntegrationInfo(
                    name="calendar-sync",
                    kind="builtin",
                    description="Two-way CalDAV calendar sync for bills, deadlines, and activities",
                    status=IntegrationStatus.configured,
                    status_detail=f"Server: {cal_status.get('server_url', '')}",
                    config_command="circuit calendar setup",
                )

        return IntegrationInfo(
            name="calendar-sync",
            kind="builtin",
            description="Two-way CalDAV calendar sync for bills, deadlines, and activities",
            status=IntegrationStatus.available,
            status_detail="caldav installed but not configured",
            requires=["caldav"],
            config_command="circuit calendar setup",
        )

    def _check_statement_linker(self) -> IntegrationInfo:
        """Statement linker is always active (built-in, no deps)."""
        return IntegrationInfo(
            name="statement-linker",
            kind="builtin",
            description="Auto-match imported transactions to known bills by pattern, amount, and date",
            status=IntegrationStatus.active,
            status_detail="Built-in, always active",
        )

    def _check_text_parser(self) -> IntegrationInfo:
        """Text parser is always active (built-in, no deps)."""
        return IntegrationInfo(
            name="text-parser",
            kind="builtin",
            description="Convert natural language text into structured financial entries",
            status=IntegrationStatus.active,
            status_detail="Built-in, always active",
            config_command="circuit add <text>",
        )

    def _check_query_engine(self) -> IntegrationInfo:
        """Query engine is always active (built-in, no deps)."""
        return IntegrationInfo(
            name="query-engine",
            kind="builtin",
            description="Answer natural language questions about your financial data",
            status=IntegrationStatus.active,
            status_detail="Built-in, always active",
            config_command="circuit query <question>",
        )
