"""Plaid financial integration CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context


@click.group(cls=JsonGroup)
@pass_context
def plaid_cmd(ctx: CircuitContext) -> None:
    """Plaid bank sync — connect accounts, sync transactions & balances."""
    pass


@plaid_cmd.command("setup")
@pass_context
def plaid_setup(ctx: CircuitContext) -> None:
    """Configure Plaid API credentials."""
    if ctx.json_mode:
        ctx.formatter.json_error("Plaid setup requires interactive mode.", code=1)
        return

    ctx.formatter.print("\n[bold cyan]Plaid Setup[/bold cyan]")
    ctx.formatter.print("Enter your Plaid API credentials (from https://dashboard.plaid.com)\n")

    client_id = click.prompt("Client ID")
    client_secret = click.prompt("Client Secret", hide_input=True)
    environment = click.prompt(
        "Environment",
        type=click.Choice(["sandbox", "development", "production"]),
        default="sandbox",
    )

    from circuitai.services.plaid_service import PlaidService

    db = ctx.get_db()
    svc = PlaidService(db)
    svc.save_credentials(client_id, client_secret, environment)
    ctx.formatter.success(f"Plaid configured ({environment} environment).")


@plaid_cmd.command("link")
@click.option("--port", default=8765, help="Local server port for Plaid Link.")
@pass_context
def plaid_link(ctx: CircuitContext, port: int) -> None:
    """Connect a bank account via Plaid Link (opens browser)."""
    if ctx.json_mode:
        ctx.formatter.json_error("Plaid Link requires interactive mode (browser).", code=1)
        return

    from circuitai.services.plaid_service import PlaidService

    db = ctx.get_db()
    svc = PlaidService(db)

    ctx.formatter.info("Creating link token...")
    link_token = svc.create_link_token()

    ctx.formatter.info(f"Opening browser on http://127.0.0.1:{port} ...")
    ctx.formatter.info("Complete the bank login in your browser.\n")

    from circuitai.services.plaid_link_server import run_link_flow

    try:
        result = run_link_flow(link_token, port=port)
    except Exception as e:
        ctx.formatter.error(str(e))
        return

    public_token = result["public_token"]
    metadata = result.get("metadata", {})

    ctx.formatter.info("Exchanging token...")
    item_id = svc.exchange_public_token(public_token, metadata)

    institution = metadata.get("institution", {}).get("name", "your bank")
    ctx.formatter.success(f"Connected to {institution} (item: {item_id[:8]}...)")
    ctx.formatter.info("Run 'circuit plaid sync' to import transactions.")


@plaid_cmd.command("sync")
@pass_context
def plaid_sync(ctx: CircuitContext) -> None:
    """Sync transactions, balances, and recurring bills from all connected banks."""
    from circuitai.services.plaid_service import PlaidService

    db = ctx.get_db()
    svc = PlaidService(db)

    if not ctx.json_mode:
        ctx.formatter.info("Syncing with Plaid...")

    try:
        results = svc.sync_all()
    except Exception as e:
        if ctx.json_mode:
            ctx.formatter.json_error(str(e))
        else:
            ctx.formatter.error(str(e))
        return

    if ctx.json_mode:
        ctx.formatter.json(results)
        return

    ctx.formatter.success(
        f"Sync complete — {results['imported']} new, {results['modified']} modified, "
        f"{results['removed']} removed, {results['updated']} balances updated, "
        f"{results['bills_created']} bills created."
    )
    for err in results.get("errors", []):
        ctx.formatter.warning(f"  {err}")


@plaid_cmd.command("status")
@pass_context
def plaid_status(ctx: CircuitContext) -> None:
    """Show connected Plaid items and sync state."""
    from circuitai.services.plaid_service import PlaidService

    db = ctx.get_db()
    svc = PlaidService(db)
    status = svc.get_status()

    if ctx.json_mode:
        ctx.formatter.json(status)
        return

    ctx.formatter.print("\n[bold cyan]Plaid Status[/bold cyan]")
    if not status["configured"]:
        ctx.formatter.warning("Not configured. Run 'circuit plaid setup' first.")
        return

    ctx.formatter.success("Credentials configured.")
    items = status["items"]
    if not items:
        ctx.formatter.info("No connected banks. Run 'circuit plaid link' to connect.")
        return

    columns = ["Item ID", "Institution", "Synced"]
    rows = []
    for item in items:
        rows.append([item["item_id"][:12] + "...", item["institution"] or "—", "Yes" if item["has_cursor"] else "No"])
    ctx.formatter.table("Connected Banks", columns, rows, data_for_json=items)


@plaid_cmd.command("identity")
@click.argument("item_id")
@pass_context
def plaid_identity(ctx: CircuitContext, item_id: str) -> None:
    """Fetch account holder identity info for a connected item."""
    from circuitai.services.plaid_service import PlaidService

    db = ctx.get_db()
    svc = PlaidService(db)

    try:
        info = svc.fetch_identity(item_id)
    except Exception as e:
        if ctx.json_mode:
            ctx.formatter.json_error(str(e))
        else:
            ctx.formatter.error(str(e))
        return

    if ctx.json_mode:
        ctx.formatter.json(info)
        return

    ctx.formatter.print(f"\n[bold cyan]Identity — {info['institution'] or item_id}[/bold cyan]")
    for acct in info["accounts"]:
        ctx.formatter.print(f"\n  Account: {acct['name']} (****{acct['mask']})")
        for owner in acct["owners"]:
            if owner["names"]:
                ctx.formatter.print(f"    Name: {', '.join(owner['names'])}")
            if owner["emails"]:
                ctx.formatter.print(f"    Email: {', '.join(owner['emails'])}")
            if owner["phones"]:
                ctx.formatter.print(f"    Phone: {', '.join(owner['phones'])}")
