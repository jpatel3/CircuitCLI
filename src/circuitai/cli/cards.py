"""Credit card management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import dollars, format_date


@click.group(cls=JsonGroup)
@pass_context
def cards(ctx: CircuitContext) -> None:
    """Manage credit cards."""
    pass


@cards.command("list")
@pass_context
def cards_list(ctx: CircuitContext) -> None:
    """List all credit cards."""
    from circuitai.services.card_service import CardService

    db = ctx.get_db()
    svc = CardService(db)
    card_list = svc.list_cards()

    if ctx.json_mode:
        ctx.formatter.json([c.model_dump() for c in card_list])
        return

    if not card_list:
        ctx.formatter.info("No credit cards found. Use 'circuit cards add' to add one.")
        return

    rows = []
    for c in card_list:
        rows.append([
            c.name,
            c.institution,
            f"****{c.last_four}" if c.last_four else "—",
            dollars(c.balance_cents),
            dollars(c.credit_limit_cents),
            f"{c.utilization_pct:.0f}%",
        ])

    ctx.formatter.table(
        title="Credit Cards",
        columns=[
            ("Name", "bold"),
            ("Institution", ""),
            ("Card", "cyan"),
            ("Balance", "red"),
            ("Limit", "green"),
            ("Util", "yellow"),
        ],
        rows=rows,
    )


@cards.command("add")
@click.option("--name", prompt="Card name", default="My Visa", help="Card name.")
@click.option("--institution", prompt="Card issuer", default="Chase", help="Card issuer.")
@click.option("--last-four", default="", help="Last 4 digits.")
@click.option("--limit", "credit_limit", type=float, default=0, help="Credit limit in dollars.")
@click.option("--balance", type=float, default=0, help="Current balance in dollars.")
@click.option("--due-day", type=int, default=None, help="Payment due day.")
@click.option("--apr", type=float, default=0, help="APR percentage (e.g., 24.99).")
@pass_context
def cards_add(
    ctx: CircuitContext,
    name: str,
    institution: str,
    last_four: str,
    credit_limit: float,
    balance: float,
    due_day: int | None,
    apr: float,
) -> None:
    """Add a new credit card."""
    from circuitai.services.card_service import CardService

    db = ctx.get_db()
    svc = CardService(db)
    card = svc.add_card(
        name=name,
        institution=institution,
        last_four=last_four,
        credit_limit_cents=int(credit_limit * 100),
        balance_cents=int(balance * 100),
        due_day=due_day,
        apr_bps=int(apr * 100),
    )

    if ctx.json_mode:
        ctx.formatter.json(card.model_dump())
    else:
        ctx.formatter.success(f"Added card: {card.name} ({card.institution})")


@cards.command("show")
@click.argument("card_id")
@pass_context
def cards_show(ctx: CircuitContext, card_id: str) -> None:
    """Show card details."""
    from circuitai.services.card_service import CardService

    db = ctx.get_db()
    svc = CardService(db)
    card = svc.get_card(card_id)
    txns = svc.get_transactions(card_id, limit=10)

    if ctx.json_mode:
        ctx.formatter.json({"card": card.model_dump(), "transactions": [t.model_dump() for t in txns]})
        return

    ctx.formatter.print(f"\n[bold]{card.name}[/bold] — {card.institution}")
    last4 = f"****{card.last_four}" if card.last_four else "—"
    ctx.formatter.print(f"  Card: {last4}")
    ctx.formatter.print(f"  Balance: {dollars(card.balance_cents)}")
    ctx.formatter.print(f"  Limit: {dollars(card.credit_limit_cents)}")
    ctx.formatter.print(f"  Utilization: {card.utilization_pct:.1f}%")
    ctx.formatter.print(f"  APR: {card.apr_bps / 100:.2f}%")
    ctx.formatter.print(f"  Due Day: {card.due_day or '—'}")

    if txns:
        ctx.formatter.print("\n  [bold]Recent Transactions:[/bold]")
        for t in txns:
            ctx.formatter.print(f"    {format_date(t.transaction_date)} {t.description}: {dollars(t.amount_cents)}")


@cards.command("update-balance")
@click.argument("card_id")
@click.option("--balance", type=float, required=True, help="New balance.")
@pass_context
def cards_update_balance(ctx: CircuitContext, card_id: str, balance: float) -> None:
    """Update card balance."""
    from circuitai.services.card_service import CardService

    db = ctx.get_db()
    svc = CardService(db)
    card = svc.update_balance(card_id, int(balance * 100))

    if ctx.json_mode:
        ctx.formatter.json(card.model_dump())
    else:
        ctx.formatter.success(f"Updated {card.name} balance: {dollars(card.balance_cents)}")


@cards.command("transactions")
@click.argument("card_id")
@click.option("--limit", type=int, default=20)
@pass_context
def cards_transactions(ctx: CircuitContext, card_id: str, limit: int) -> None:
    """Show card transactions."""
    from circuitai.services.card_service import CardService

    db = ctx.get_db()
    svc = CardService(db)
    txns = svc.get_transactions(card_id, limit=limit)

    if ctx.json_mode:
        ctx.formatter.json([t.model_dump() for t in txns])
        return

    if not txns:
        ctx.formatter.info("No transactions found.")
        return

    rows = [[format_date(t.transaction_date), t.description, dollars(t.amount_cents), t.category or "—"] for t in txns]
    ctx.formatter.table(
        title="Card Transactions",
        columns=[("Date", ""), ("Description", "bold"), ("Amount", "red"), ("Category", "dim")],
        rows=rows,
    )
