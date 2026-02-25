"""Mortgage management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import dollars


@click.group(cls=JsonGroup)
@pass_context
def mortgage(ctx: CircuitContext) -> None:
    """Mortgage tracking and management."""
    pass


@mortgage.command("list")
@pass_context
def mortgage_list(ctx: CircuitContext) -> None:
    """List all mortgages."""
    from circuitai.services.mortgage_service import MortgageService

    db = ctx.get_db()
    svc = MortgageService(db)
    mtgs = svc.list_mortgages()

    if ctx.json_mode:
        ctx.formatter.json([m.model_dump() for m in mtgs])
        return

    if not mtgs:
        ctx.formatter.info(
            "No mortgages found. Add one with:\n\n"
            "  /mortgage add --name 'Home Loan' --lender 'Wells Fargo'\n"
            "    --original-amount 350000 --balance 280000\n"
            "    --rate 6.5 --payment 2200"
        )
        return

    rows = []
    for m in mtgs:
        rows.append([
            m.name, m.lender, dollars(m.balance_cents),
            dollars(m.monthly_payment_cents), f"{m.interest_rate_pct}%",
        ])

    ctx.formatter.table(
        title="Mortgages",
        columns=[("Name", "bold"), ("Lender", ""), ("Balance", "red"), ("Payment", "yellow"), ("Rate", "cyan")],
        rows=rows,
    )


@mortgage.command("add")
@click.option("--name", required=True)
@click.option("--lender", required=True)
@click.option("--original-amount", type=float, required=True, help="Original loan amount in dollars.")
@click.option("--balance", type=float, required=True, help="Current balance in dollars.")
@click.option("--rate", type=float, required=True, help="Interest rate percentage (e.g., 6.5).")
@click.option("--payment", type=float, required=True, help="Monthly payment in dollars.")
@click.option("--escrow", type=float, default=0, help="Monthly escrow in dollars.")
@click.option("--term", type=int, default=360, help="Loan term in months.")
@click.option("--start-date", default="", help="Loan start date (YYYY-MM-DD).")
@click.option("--due-day", type=int, default=1)
@pass_context
def mortgage_add(ctx: CircuitContext, **kwargs) -> None:
    """Add a new mortgage."""
    from circuitai.services.mortgage_service import MortgageService

    db = ctx.get_db()
    svc = MortgageService(db)
    mtg = svc.add_mortgage(
        name=kwargs["name"],
        lender=kwargs["lender"],
        original_amount_cents=int(kwargs["original_amount"] * 100),
        balance_cents=int(kwargs["balance"] * 100),
        interest_rate_bps=int(kwargs["rate"] * 100),
        monthly_payment_cents=int(kwargs["payment"] * 100),
        escrow_cents=int(kwargs["escrow"] * 100),
        term_months=kwargs["term"],
        start_date=kwargs["start_date"],
        due_day=kwargs["due_day"],
    )

    if ctx.json_mode:
        ctx.formatter.json(mtg.model_dump())
    else:
        ctx.formatter.success(f"Added mortgage: {mtg.name} ({mtg.lender}) — {dollars(mtg.balance_cents)}")


@mortgage.command("show")
@click.argument("mortgage_id")
@pass_context
def mortgage_show(ctx: CircuitContext, mortgage_id: str) -> None:
    """Show mortgage details."""
    from circuitai.services.mortgage_service import MortgageService

    db = ctx.get_db()
    svc = MortgageService(db)
    mtg = svc.get_mortgage(mortgage_id)
    payments = svc.get_payments(mortgage_id, limit=6)

    if ctx.json_mode:
        ctx.formatter.json({"mortgage": mtg.model_dump(), "payments": [p.model_dump() for p in payments]})
        return

    ctx.formatter.print(f"\n[bold]{mtg.name}[/bold] — {mtg.lender}")
    ctx.formatter.print(f"  Original: {dollars(mtg.original_amount_cents)}")
    ctx.formatter.print(f"  Balance: {dollars(mtg.balance_cents)}")
    ctx.formatter.print(f"  Payment: {dollars(mtg.monthly_payment_cents)}/mo")
    ctx.formatter.print(f"  Rate: {mtg.interest_rate_pct}%")
    ctx.formatter.print(f"  Term: {mtg.term_months} months")
    ctx.formatter.print(f"  Due Day: {mtg.due_day}")


@mortgage.command("pay")
@click.argument("mortgage_id")
@click.option("--amount", type=float, default=None)
@click.option("--principal", type=float, default=0)
@click.option("--interest", type=float, default=0)
@click.option("--escrow", type=float, default=0)
@click.option("--date", "paid_date", default=None)
@pass_context
def mortgage_pay(ctx: CircuitContext, mortgage_id: str, amount, principal, interest, escrow, paid_date) -> None:
    """Record a mortgage payment."""
    from circuitai.services.mortgage_service import MortgageService

    db = ctx.get_db()
    svc = MortgageService(db)
    payment = svc.make_payment(
        mortgage_id=mortgage_id,
        amount_cents=int(amount * 100) if amount else None,
        principal_cents=int(principal * 100),
        interest_cents=int(interest * 100),
        escrow_cents=int(escrow * 100),
        paid_date=paid_date,
    )

    if ctx.json_mode:
        ctx.formatter.json(payment.model_dump())
    else:
        ctx.formatter.success(f"Recorded payment: {dollars(payment.amount_cents)}")


@mortgage.command("amortization")
@click.argument("mortgage_id")
@click.option("--months", type=int, default=12, help="Number of months to project.")
@pass_context
def mortgage_amortization(ctx: CircuitContext, mortgage_id: str, months: int) -> None:
    """Show amortization schedule."""
    from circuitai.services.mortgage_service import MortgageService

    db = ctx.get_db()
    svc = MortgageService(db)
    schedule = svc.get_amortization_schedule(mortgage_id, months=months)

    if ctx.json_mode:
        ctx.formatter.json(schedule)
        return

    rows = []
    for entry in schedule:
        rows.append([
            str(entry["month"]),
            dollars(entry["payment_cents"]),
            dollars(entry["principal_cents"]),
            dollars(entry["interest_cents"]),
            dollars(entry["remaining_balance_cents"]),
        ])

    ctx.formatter.table(
        title="Amortization Schedule",
        columns=[("Month", ""), ("Payment", ""), ("Principal", "green"), ("Interest", "red"), ("Balance", "yellow")],
        rows=rows,
    )
