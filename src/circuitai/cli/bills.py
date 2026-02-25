"""Bill management CLI commands."""

from __future__ import annotations

from datetime import date

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import dollars, format_date


@click.group(cls=JsonGroup)
@pass_context
def bills(ctx: CircuitContext) -> None:
    """Manage bills (list, add, show, pay, edit, delete, summary)."""
    pass


@bills.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include inactive bills.")
@pass_context
def bills_list(ctx: CircuitContext, show_all: bool) -> None:
    """List all bills."""
    from circuitai.services.bill_service import BillService

    db = ctx.get_db()
    svc = BillService(db)
    bill_list = svc.list_bills(active_only=not show_all)

    if ctx.json_mode:
        ctx.formatter.json([b.model_dump() for b in bill_list])
        return

    if not bill_list:
        ctx.formatter.info("No bills found. Use 'circuit bills add' to add one.")
        return

    rows = []
    json_data = []
    for b in bill_list:
        last = svc.get_last_payment(b.id)
        status = "Paid" if last and (date.today() - date.fromisoformat(last.paid_date[:10])).days < 25 else "Upcoming"
        rows.append([
            b.name,
            b.provider,
            dollars(b.amount_cents),
            str(b.due_day or "—"),
            b.frequency,
            status,
        ])
        json_data.append({**b.model_dump(), "status": status})

    ctx.formatter.table(
        title="Bills",
        columns=[
            ("Name", "bold"),
            ("Provider", ""),
            ("Amount", "green"),
            ("Due Day", "cyan"),
            ("Frequency", "dim"),
            ("Status", "yellow"),
        ],
        rows=rows,
        data_for_json=json_data,
    )


@bills.command("add")
@click.option("--name", prompt="Bill name", default="Electric Bill", help="Bill name.")
@click.option("--provider", default="", help="Provider/company name.")
@click.option("--category", default="other", help="Category (electricity, water, gas, internet, etc.).")
@click.option("--amount", type=float, prompt="Amount in dollars", default=0, help="Amount in dollars.")
@click.option("--due-day", type=int, default=None, help="Day of month bill is due (1-31).")
@click.option("--frequency", default="monthly", help="Frequency: monthly, quarterly, yearly, one-time.")
@click.option("--auto-pay/--no-auto-pay", default=False, help="Whether this bill is on auto-pay.")
@click.option("--notes", default="", help="Notes.")
@pass_context
def bills_add(
    ctx: CircuitContext,
    name: str,
    provider: str,
    category: str,
    amount: float,
    due_day: int | None,
    frequency: str,
    auto_pay: bool,
    notes: str,
) -> None:
    """Add a new bill."""
    from circuitai.services.bill_service import BillService

    db = ctx.get_db()
    svc = BillService(db)
    bill = svc.add_bill(
        name=name,
        provider=provider,
        category=category,
        amount_cents=int(amount * 100),
        due_day=due_day,
        frequency=frequency,
        auto_pay=auto_pay,
        notes=notes,
    )

    if ctx.json_mode:
        ctx.formatter.json(bill.model_dump())
    else:
        ctx.formatter.success(f"Added bill: {bill.name}, {dollars(bill.amount_cents)}, due day {bill.due_day or '—'}")


@bills.command("show")
@click.argument("bill_id")
@pass_context
def bills_show(ctx: CircuitContext, bill_id: str) -> None:
    """Show details for a specific bill."""
    from circuitai.services.bill_service import BillService

    db = ctx.get_db()
    svc = BillService(db)

    # Try ID or name search
    try:
        bill = svc.get_bill(bill_id)
    except Exception:
        results = svc.search_bills(bill_id)
        if results:
            bill = results[0]
        else:
            ctx.formatter.error(f"Bill not found: {bill_id}")
            return

    payments = svc.get_payments(bill.id, limit=5)

    if ctx.json_mode:
        ctx.formatter.json({
            "bill": bill.model_dump(),
            "recent_payments": [p.model_dump() for p in payments],
        })
        return

    ctx.formatter.print(f"\n[bold]{bill.name}[/bold]")
    ctx.formatter.print(f"  Provider: {bill.provider}")
    ctx.formatter.print(f"  Category: {bill.category}")
    ctx.formatter.print(f"  Amount: {dollars(bill.amount_cents)}")
    ctx.formatter.print(f"  Due Day: {bill.due_day or '—'}")
    ctx.formatter.print(f"  Frequency: {bill.frequency}")
    ctx.formatter.print(f"  Auto-pay: {'Yes' if bill.auto_pay else 'No'}")
    ctx.formatter.print(f"  ID: {bill.id}")

    if payments:
        ctx.formatter.print("\n  [bold]Recent Payments:[/bold]")
        for p in payments:
            ctx.formatter.print(f"    {format_date(p.paid_date)} — {dollars(p.amount_cents)}")


@bills.command("pay")
@click.argument("bill_id")
@click.option("--amount", type=float, default=None, help="Payment amount (defaults to bill amount).")
@click.option("--date", "paid_date", default=None, help="Payment date (YYYY-MM-DD, defaults to today).")
@click.option("--method", default="", help="Payment method.")
@click.option("--confirmation", default="", help="Confirmation number.")
@pass_context
def bills_pay(
    ctx: CircuitContext,
    bill_id: str,
    amount: float | None,
    paid_date: str | None,
    method: str,
    confirmation: str,
) -> None:
    """Record a payment for a bill."""
    from circuitai.services.bill_service import BillService

    db = ctx.get_db()
    svc = BillService(db)

    # Try ID or name search
    try:
        bill = svc.get_bill(bill_id)
    except Exception:
        results = svc.search_bills(bill_id)
        if results:
            bill = results[0]
        else:
            ctx.formatter.error(f"Bill not found: {bill_id}")
            return

    payment = svc.pay_bill(
        bill_id=bill.id,
        amount_cents=int(amount * 100) if amount else None,
        paid_date=paid_date,
        payment_method=method,
        confirmation=confirmation,
    )

    if ctx.json_mode:
        ctx.formatter.json(payment.model_dump())
    else:
        ctx.formatter.success(
            f"Recorded payment: {dollars(payment.amount_cents)} for {bill.name} on {format_date(payment.paid_date)}"
        )


@bills.command("edit")
@click.argument("bill_id")
@click.option("--name", default=None)
@click.option("--provider", default=None)
@click.option("--category", default=None)
@click.option("--amount", type=float, default=None)
@click.option("--due-day", type=int, default=None)
@click.option("--frequency", default=None)
@pass_context
def bills_edit(ctx: CircuitContext, bill_id: str, **kwargs: str | float | int | None) -> None:
    """Edit a bill."""
    from circuitai.services.bill_service import BillService

    db = ctx.get_db()
    svc = BillService(db)

    updates = {k: v for k, v in kwargs.items() if v is not None}
    if "amount" in updates:
        updates["amount_cents"] = int(float(updates.pop("amount")) * 100)
    if "due_day" in updates:
        updates["due_day"] = int(updates["due_day"])

    if not updates:
        ctx.formatter.warning("No updates specified.")
        return

    bill = svc.update_bill(bill_id, **updates)

    if ctx.json_mode:
        ctx.formatter.json(bill.model_dump())
    else:
        ctx.formatter.success(f"Updated bill: {bill.name}")


@bills.command("delete")
@click.argument("bill_id")
@click.option("--confirm", is_flag=True, help="Skip confirmation prompt.")
@pass_context
def bills_delete(ctx: CircuitContext, bill_id: str, confirm: bool) -> None:
    """Delete (deactivate) a bill."""
    from circuitai.services.bill_service import BillService

    db = ctx.get_db()
    svc = BillService(db)

    bill = svc.get_bill(bill_id)
    if not confirm and not ctx.json_mode:
        if not click.confirm(f"Delete bill '{bill.name}'?"):
            ctx.formatter.info("Cancelled.")
            return

    svc.delete_bill(bill_id)

    if ctx.json_mode:
        ctx.formatter.json({"deleted": bill_id})
    else:
        ctx.formatter.success(f"Deleted bill: {bill.name}")


@bills.command("summary")
@pass_context
def bills_summary(ctx: CircuitContext) -> None:
    """Show a summary of all bills."""
    from circuitai.services.bill_service import BillService

    db = ctx.get_db()
    svc = BillService(db)
    summary = svc.get_summary()

    if ctx.json_mode:
        ctx.formatter.json(summary)
        return

    ctx.formatter.print("\n[bold cyan]Bills Summary[/bold cyan]")
    ctx.formatter.print(f"  Total active bills: {summary['total_bills']}")
    ctx.formatter.print(f"  Monthly total: {dollars(summary['monthly_total_cents'])}")
    ctx.formatter.print(f"  Quarterly total: {dollars(summary['quarterly_total_cents'])}")
    ctx.formatter.print(f"  Yearly total: {dollars(summary['yearly_total_cents'])}")
    ctx.formatter.print(f"  Estimated monthly (all): {dollars(summary['estimated_monthly_cents'])}")
    ctx.formatter.print(f"  Due this week: {summary['due_soon']}")


@bills.command("link")
@click.option("--account", "account_id", default=None, help="Limit to a specific account ID.")
@click.option("--tolerance", type=float, default=5.0, help="Amount tolerance in dollars.")
@click.option("--days", "date_window", type=int, default=7, help="Date proximity window in days.")
@pass_context
def bills_link(
    ctx: CircuitContext, account_id: str | None, tolerance: float, date_window: int
) -> None:
    """Auto-match transactions to bills (statement linking)."""
    from circuitai.services.statement_linker import StatementLinker

    db = ctx.get_db()
    linker = StatementLinker(
        db,
        amount_tolerance_cents=int(tolerance * 100),
        date_window_days=date_window,
    )
    result = linker.link_transactions(account_id=account_id)

    if ctx.json_mode:
        ctx.formatter.json(result)
        return

    if result["matched"] == 0:
        ctx.formatter.info(f"No new matches found ({result['total_unmatched']} unmatched transactions).")
    else:
        ctx.formatter.success(f"Matched {result['matched']} of {result['total_unmatched']} transactions.")
        for m in result["matches"]:
            ctx.formatter.print(f"  {m['description']} → bill {m['bill_id'][:8]}… (score: {m['score']:.2f})")


@bills.command("unmatched")
@click.option("--account", "account_id", default=None, help="Limit to a specific account ID.")
@pass_context
def bills_unmatched(ctx: CircuitContext, account_id: str | None) -> None:
    """Show unmatched transactions for review."""
    from circuitai.services.statement_linker import StatementLinker

    db = ctx.get_db()
    linker = StatementLinker(db)
    unmatched = linker.get_unmatched(account_id=account_id)

    if ctx.json_mode:
        ctx.formatter.json(unmatched)
        return

    if not unmatched:
        ctx.formatter.info("No unmatched transactions.")
        return

    rows = []
    for t in unmatched:
        rows.append([
            t["transaction_date"],
            t["description"],
            dollars(abs(t["amount_cents"])),
            t["id"][:8] + "…",
        ])

    ctx.formatter.table(
        title="Unmatched Transactions",
        columns=[("Date", ""), ("Description", "bold"), ("Amount", "green"), ("ID", "dim")],
        rows=rows,
    )


@bills.command("confirm-match")
@click.argument("transaction_id")
@click.argument("bill_id")
@pass_context
def bills_confirm_match(ctx: CircuitContext, transaction_id: str, bill_id: str) -> None:
    """Manually confirm a transaction-to-bill match (teaches the system)."""
    from circuitai.services.statement_linker import StatementLinker

    db = ctx.get_db()
    linker = StatementLinker(db)
    linker.confirm_match(transaction_id, bill_id)

    if ctx.json_mode:
        ctx.formatter.json({"confirmed": True, "transaction_id": transaction_id, "bill_id": bill_id})
    else:
        ctx.formatter.success("Confirmed match and learned pattern.")
