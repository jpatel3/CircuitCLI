"""Dual-mode output — Rich for humans, JSON for agents."""

from __future__ import annotations

import json
import sys
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Human output goes to stdout; in JSON mode, human messages go to stderr
_console = Console()
_err_console = Console(stderr=True)


class OutputFormatter:
    """Routes output to Rich (human) or JSON (agent) depending on mode."""

    def __init__(self, json_mode: bool = False) -> None:
        self.json_mode = json_mode

    # ── JSON output ──────────────────────────────────────────────

    def json(self, data: Any, status: str = "success") -> None:
        """Print structured JSON to stdout."""
        envelope = {"status": status, "data": data}
        print(json.dumps(envelope, indent=2, default=str))

    def json_error(self, message: str, code: int = 1) -> None:
        """Print a JSON error envelope to stdout."""
        envelope = {"status": "error", "error": {"message": message, "code": code}}
        print(json.dumps(envelope, indent=2))

    # ── Human output ─────────────────────────────────────────────

    def print(self, message: str = "", **kwargs: Any) -> None:
        """Print a message, routing to stderr in JSON mode."""
        console = _err_console if self.json_mode else _console
        console.print(message, **kwargs)

    def success(self, message: str) -> None:
        """Print a success message."""
        if self.json_mode:
            return
        _console.print(f"[green]✓[/green] {message}")

    def warning(self, message: str) -> None:
        """Print a warning."""
        console = _err_console if self.json_mode else _console
        console.print(f"[yellow]![/yellow] {message}")

    def error(self, message: str) -> None:
        """Print an error message."""
        console = _err_console if self.json_mode else _console
        console.print(f"[red]✗[/red] {message}")

    def info(self, message: str) -> None:
        """Print an info message."""
        if self.json_mode:
            return
        _console.print(f"[dim]ℹ[/dim] {message}")

    def table(
        self,
        title: str,
        columns: list[tuple[str, str]],
        rows: list[list[str]],
        data_for_json: list[dict[str, Any]] | None = None,
    ) -> None:
        """Print a table (Rich for humans, JSON for agents).

        columns: list of (header, style) tuples
        rows: list of row data (strings)
        data_for_json: if provided, used as the JSON payload instead of rows
        """
        if self.json_mode:
            self.json(data_for_json or [dict(zip([c[0] for c in columns], r)) for r in rows])
            return

        table = Table(title=title, show_header=True, header_style="bold cyan")
        for header, style in columns:
            table.add_column(header, style=style)
        for row in rows:
            table.add_row(*row)
        _console.print(table)

    def panel(self, content: str, title: str = "", border_style: str = "blue") -> None:
        """Print a Rich panel."""
        if self.json_mode:
            return
        _console.print(Panel(content, title=title, border_style=border_style))

    def rule(self, title: str = "") -> None:
        """Print a horizontal rule."""
        if self.json_mode:
            return
        _console.rule(title)


def dollars(cents: int) -> str:
    """Format cents as a dollar string."""
    negative = cents < 0
    abs_cents = abs(cents)
    s = f"${abs_cents // 100:,}.{abs_cents % 100:02d}"
    return f"-{s}" if negative else s


def format_date(date_str: str | None) -> str:
    """Format an ISO date string for display."""
    if not date_str:
        return "—"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(date_str)
        return dt.strftime("%b %d, %Y")
    except (ValueError, TypeError):
        return date_str or "—"
