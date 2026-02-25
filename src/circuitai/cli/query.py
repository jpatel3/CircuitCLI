"""Natural language query CLI command."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, pass_context


@click.command()
@click.argument("text", nargs=-1, required=True)
@pass_context
def query(ctx: CircuitContext, text: tuple[str, ...]) -> None:
    """Ask a question about your finances.

    Examples:
        circuit query "what bills are due this week?"
        circuit query "what's my electricity bill?"
        circuit query "show my account balances"
    """
    from circuitai.services.query_service import QueryService

    full_text = " ".join(text)
    db = ctx.get_db()
    svc = QueryService(db)

    if ctx.json_mode:
        ctx.formatter.json(svc.query_json(full_text))
    else:
        result = svc.query(full_text)
        ctx.formatter.print(result)
