"""Bank account management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import dollars, format_date


@click.group(cls=JsonGroup)
@pass_context
def accounts(ctx: CircuitContext) -> None:
    """Manage bank accounts."""
    pass


@accounts.command("list")
@pass_context
def accounts_list(ctx: CircuitContext) -> None:
    """List all bank accounts."""
    from circuitai.services.account_service import AccountService

    db = ctx.get_db()
    svc = AccountService(db)
    accts = svc.list_accounts()

    if ctx.json_mode:
        ctx.formatter.json([a.model_dump() for a in accts])
        return

    if not accts:
        ctx.formatter.info("No bank accounts found. Use 'circuit accounts add' to add one.")
        return

    rows = []
    for a in accts:
        last4 = f"****{a.last_four}" if a.last_four else "—"
        rows.append([a.name, a.institution, a.account_type, last4, dollars(a.balance_cents)])

    ctx.formatter.table(
        title="Bank Accounts",
        columns=[
            ("Name", "bold"),
            ("Institution", ""),
            ("Type", "dim"),
            ("Last 4", "cyan"),
            ("Balance", "green"),
        ],
        rows=rows,
    )
    ctx.formatter.print(f"\n  Total: {dollars(svc.get_total_balance())}")


@accounts.command("add")
@click.option("--name", required=True, help="Account name.")
@click.option("--institution", required=True, help="Bank name.")
@click.option("--type", "account_type", default="checking", help="Account type: checking, savings, money_market.")
@click.option("--last-four", default="", help="Last 4 digits of account number.")
@click.option("--balance", type=float, default=0, help="Current balance in dollars.")
@click.option("--notes", default="", help="Notes.")
@pass_context
def accounts_add(
    ctx: CircuitContext,
    name: str,
    institution: str,
    account_type: str,
    last_four: str,
    balance: float,
    notes: str,
) -> None:
    """Add a new bank account."""
    from circuitai.services.account_service import AccountService

    db = ctx.get_db()
    svc = AccountService(db)
    acct = svc.add_account(
        name=name,
        institution=institution,
        account_type=account_type,
        last_four=last_four,
        balance_cents=int(balance * 100),
        notes=notes,
    )

    if ctx.json_mode:
        ctx.formatter.json(acct.model_dump())
    else:
        ctx.formatter.success(f"Added account: {acct.name} ({acct.institution}) — {dollars(acct.balance_cents)}")


@accounts.command("show")
@click.argument("account_id")
@pass_context
def accounts_show(ctx: CircuitContext, account_id: str) -> None:
    """Show account details and recent transactions."""
    from circuitai.services.account_service import AccountService

    db = ctx.get_db()
    svc = AccountService(db)
    acct = svc.get_account(account_id)
    txns = svc.get_transactions(account_id, limit=10)

    if ctx.json_mode:
        ctx.formatter.json({
            "account": acct.model_dump(),
            "transactions": [t.model_dump() for t in txns],
        })
        return

    ctx.formatter.print(f"\n[bold]{acct.name}[/bold] — {acct.institution}")
    ctx.formatter.print(f"  Type: {acct.account_type}")
    last4 = f"****{acct.last_four}" if acct.last_four else "—"
    ctx.formatter.print(f"  Account: {last4}")
    ctx.formatter.print(f"  Balance: {dollars(acct.balance_cents)}")
    ctx.formatter.print(f"  ID: {acct.id}")

    if txns:
        ctx.formatter.print("\n  [bold]Recent Transactions:[/bold]")
        for t in txns:
            sign = "+" if t.amount_cents > 0 else ""
            ctx.formatter.print(
                f"    {format_date(t.transaction_date)} {t.description}:"
                f" {sign}{dollars(t.amount_cents)}"
            )


@accounts.command("update-balance")
@click.argument("account_id")
@click.option("--balance", type=float, required=True, help="New balance in dollars.")
@pass_context
def accounts_update_balance(ctx: CircuitContext, account_id: str, balance: float) -> None:
    """Update the balance of an account."""
    from circuitai.services.account_service import AccountService

    db = ctx.get_db()
    svc = AccountService(db)
    acct = svc.update_balance(account_id, int(balance * 100))

    if ctx.json_mode:
        ctx.formatter.json(acct.model_dump())
    else:
        ctx.formatter.success(f"Updated {acct.name} balance: {dollars(acct.balance_cents)}")


@accounts.command("transactions")
@click.argument("account_id")
@click.option("--limit", type=int, default=20, help="Number of transactions to show.")
@pass_context
def accounts_transactions(ctx: CircuitContext, account_id: str, limit: int) -> None:
    """Show transactions for an account."""
    from circuitai.services.account_service import AccountService

    db = ctx.get_db()
    svc = AccountService(db)
    txns = svc.get_transactions(account_id, limit=limit)

    if ctx.json_mode:
        ctx.formatter.json([t.model_dump() for t in txns])
        return

    if not txns:
        ctx.formatter.info("No transactions found.")
        return

    rows = []
    for t in txns:
        sign = "+" if t.amount_cents > 0 else ""
        rows.append([
            format_date(t.transaction_date), t.description,
            f"{sign}{dollars(t.amount_cents)}", t.category or "—",
        ])

    ctx.formatter.table(
        title="Transactions",
        columns=[("Date", ""), ("Description", "bold"), ("Amount", "green"), ("Category", "dim")],
        rows=rows,
    )
