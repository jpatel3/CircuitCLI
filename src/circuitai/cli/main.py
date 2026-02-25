"""Root CLI group — entry point for all CircuitAI commands."""

from __future__ import annotations

import sys
from typing import Any

import click

from circuitai import __version__
from circuitai.output.formatter import OutputFormatter


class CircuitContext:
    """Shared context passed through Click commands."""

    def __init__(self, json_mode: bool = False) -> None:
        self.json_mode = json_mode
        self.formatter = OutputFormatter(json_mode=json_mode)
        self._db = None
        self._key: str | None = None

    def get_db(self):
        """Lazy-load and return the database connection."""
        if self._db is None:
            from circuitai.core.database import DatabaseConnection
            from circuitai.core.config import get_data_dir

            self._db = DatabaseConnection(encryption_key=self._key)
            self._db.connect()
        return self._db

    def set_key(self, key: str) -> None:
        """Set the encryption key for database access."""
        self._key = key

    def close(self) -> None:
        """Close the database connection."""
        if self._db is not None:
            self._db.close()


pass_context = click.make_pass_decorator(CircuitContext, ensure=True)


@click.group(invoke_without_command=True)
@click.option("--json", "json_mode", is_flag=True, help="Output JSON for agent consumption.")
@click.version_option(__version__, prog_name="CircuitAI")
@click.pass_context
def cli(ctx: click.Context, json_mode: bool) -> None:
    """CircuitAI — Local-first, privacy-focused personal finance CLI.

    Run without a subcommand to launch the interactive REPL.
    """
    ctx.ensure_object(CircuitContext)
    ctx.obj = CircuitContext(json_mode=json_mode)

    if ctx.invoked_subcommand is None:
        # No subcommand → launch interactive REPL
        from circuitai.cli.repl import launch_repl
        launch_repl(ctx.obj)


# ── Register subcommands ──────────────────────────────────────────

from circuitai.cli.setup import setup_cmd
cli.add_command(setup_cmd, "setup")

from circuitai.cli.bills import bills
cli.add_command(bills)

from circuitai.cli.accounts import accounts
cli.add_command(accounts)

from circuitai.cli.cards import cards
cli.add_command(cards)

from circuitai.cli.mortgage import mortgage
cli.add_command(mortgage)

from circuitai.cli.investments import investments
cli.add_command(investments)

from circuitai.cli.deadlines import deadlines
cli.add_command(deadlines)

from circuitai.cli.activities import activities
cli.add_command(activities)

from circuitai.cli.morning import morning
cli.add_command(morning)

from circuitai.cli.add_text import add_cmd
cli.add_command(add_cmd, "add")

from circuitai.cli.query import query
cli.add_command(query)

from circuitai.cli.dashboard import dashboard
cli.add_command(dashboard)

from circuitai.cli.adapters_cmd import adapters
cli.add_command(adapters)

from circuitai.cli.calendar_cmd import calendar
cli.add_command(calendar)

from circuitai.cli.export import export
cli.add_command(export)
