"""Investment account management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, pass_context
from circuitai.output.formatter import dollars, format_date


@click.group()
@pass_context
def investments(ctx: CircuitContext) -> None:
    """Manage investment accounts."""
    pass


@investments.command("list")
@pass_context
def investments_list(ctx: CircuitContext) -> None:
    """List all investment accounts."""
    from circuitai.services.investment_service import InvestmentService

    db = ctx.get_db()
    svc = InvestmentService(db)
    inv_list = svc.list_investments()

    if ctx.json_mode:
        ctx.formatter.json([i.model_dump() for i in inv_list])
        return

    if not inv_list:
        ctx.formatter.info("No investment accounts found.")
        return

    rows = []
    for i in inv_list:
        gain = dollars(i.gain_loss_cents)
        pct = f"{i.gain_loss_pct:+.1f}%"
        rows.append([
            i.name, i.institution, i.account_type,
            dollars(i.current_value_cents), f"{gain} ({pct})",
        ])

    ctx.formatter.table(
        title="Investments",
        columns=[("Name", "bold"), ("Institution", ""), ("Type", "dim"), ("Value", "green"), ("Gain/Loss", "yellow")],
        rows=rows,
    )
    ctx.formatter.print(f"\n  Total: {dollars(svc.get_total_value())}")


@investments.command("add")
@click.option("--name", required=True)
@click.option("--institution", required=True)
@click.option("--type", "account_type", default="brokerage", help="Type: brokerage, 401k, 529, ira, roth_ira, hsa, crypto.")
@click.option("--value", type=float, default=0, help="Current value in dollars.")
@click.option("--cost-basis", type=float, default=0, help="Cost basis in dollars.")
@click.option("--recurring", type=float, default=0, help="Recurring contribution in dollars.")
@click.option("--frequency", default="monthly")
@click.option("--notes", default="")
@pass_context
def investments_add(ctx: CircuitContext, name, institution, account_type, value, cost_basis, recurring, frequency, notes) -> None:
    """Add a new investment account."""
    from circuitai.services.investment_service import InvestmentService

    db = ctx.get_db()
    svc = InvestmentService(db)
    inv = svc.add_investment(
        name=name,
        institution=institution,
        account_type=account_type,
        current_value_cents=int(value * 100),
        cost_basis_cents=int(cost_basis * 100),
        recurring_amount_cents=int(recurring * 100),
        recurring_frequency=frequency,
        notes=notes,
    )

    if ctx.json_mode:
        ctx.formatter.json(inv.model_dump())
    else:
        ctx.formatter.success(f"Added investment: {inv.name} ({inv.institution}) — {dollars(inv.current_value_cents)}")


@investments.command("show")
@click.argument("investment_id")
@pass_context
def investments_show(ctx: CircuitContext, investment_id: str) -> None:
    """Show investment details."""
    from circuitai.services.investment_service import InvestmentService

    db = ctx.get_db()
    svc = InvestmentService(db)
    inv = svc.get_investment(investment_id)
    contribs = svc.get_contributions(investment_id, limit=10)

    if ctx.json_mode:
        ctx.formatter.json({"investment": inv.model_dump(), "contributions": [c.model_dump() for c in contribs]})
        return

    ctx.formatter.print(f"\n[bold]{inv.name}[/bold] — {inv.institution}")
    ctx.formatter.print(f"  Type: {inv.account_type}")
    ctx.formatter.print(f"  Value: {dollars(inv.current_value_cents)}")
    ctx.formatter.print(f"  Cost Basis: {dollars(inv.cost_basis_cents)}")
    ctx.formatter.print(f"  Gain/Loss: {dollars(inv.gain_loss_cents)} ({inv.gain_loss_pct:+.1f}%)")
    if inv.recurring_amount_cents:
        ctx.formatter.print(f"  Recurring: {dollars(inv.recurring_amount_cents)}/{inv.recurring_frequency}")

    if contribs:
        ctx.formatter.print("\n  [bold]Recent Contributions:[/bold]")
        for c in contribs:
            ctx.formatter.print(f"    {format_date(c.contribution_date)} — {dollars(c.amount_cents)}")


@investments.command("contribute")
@click.argument("investment_id")
@click.option("--amount", type=float, required=True, help="Contribution amount in dollars.")
@click.option("--date", "contribution_date", default=None)
@click.option("--notes", default="")
@pass_context
def investments_contribute(ctx: CircuitContext, investment_id, amount, contribution_date, notes) -> None:
    """Record a contribution."""
    from circuitai.services.investment_service import InvestmentService

    db = ctx.get_db()
    svc = InvestmentService(db)
    contrib = svc.contribute(
        investment_id=investment_id,
        amount_cents=int(amount * 100),
        contribution_date=contribution_date,
        notes=notes,
    )

    if ctx.json_mode:
        ctx.formatter.json(contrib.model_dump())
    else:
        ctx.formatter.success(f"Recorded contribution: {dollars(contrib.amount_cents)}")


@investments.command("performance")
@pass_context
def investments_performance(ctx: CircuitContext) -> None:
    """Show overall investment performance."""
    from circuitai.services.investment_service import InvestmentService

    db = ctx.get_db()
    svc = InvestmentService(db)
    perf = svc.get_performance()

    if ctx.json_mode:
        ctx.formatter.json(perf)
        return

    ctx.formatter.print("\n[bold cyan]Investment Performance[/bold cyan]")
    ctx.formatter.print(f"  Total Value: {dollars(perf['total_value_cents'])}")
    ctx.formatter.print(f"  Cost Basis: {dollars(perf['total_cost_basis_cents'])}")
    ctx.formatter.print(f"  Gain/Loss: {dollars(perf['total_gain_loss_cents'])} ({perf['gain_loss_pct']:+.1f}%)")
    ctx.formatter.print(f"  Accounts: {perf['count']}")
    if perf["by_type"]:
        ctx.formatter.print("\n  By Type:")
        for t, v in perf["by_type"].items():
            ctx.formatter.print(f"    {t}: {dollars(v)}")
