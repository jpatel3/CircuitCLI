"""Textual TUI dashboard launcher."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, pass_context


@click.command()
@pass_context
def dashboard(ctx: CircuitContext) -> None:
    """Launch the full Textual TUI dashboard."""
    try:
        from circuitai.tui.app import CircuitDashboard

        db = ctx.get_db()
        app = CircuitDashboard(db=db)
        app.run()
    except ImportError as e:
        ctx.formatter.error(f"Dashboard requires textual: {e}")
    except Exception as e:
        ctx.formatter.error(f"Dashboard error: {e}")
