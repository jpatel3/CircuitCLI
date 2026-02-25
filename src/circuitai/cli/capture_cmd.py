"""Screen capture CLI commands — screenshot, extract, and import bank data."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context


@click.group(cls=JsonGroup)
@pass_context
def capture(ctx: CircuitContext) -> None:
    """Screen capture — screenshot bank pages, extract & import transactions."""
    pass


@capture.command("setup")
@pass_context
def capture_setup(ctx: CircuitContext) -> None:
    """Configure Anthropic API key for vision extraction."""
    if ctx.json_mode:
        ctx.formatter.json_error("Capture setup requires interactive mode.", code=1)
        return

    ctx.formatter.print("\n[bold cyan]Capture Setup[/bold cyan]")
    ctx.formatter.print("Enter your Anthropic API key (from https://console.anthropic.com)\n")

    api_key = click.prompt("Anthropic API key", hide_input=True)
    if not api_key.strip():
        ctx.formatter.warning("No API key provided. Capture not configured.")
        return

    from circuitai.services.capture_service import CaptureService

    db = ctx.get_db()
    svc = CaptureService(db)
    svc.save_api_key(api_key.strip())
    ctx.formatter.success("Anthropic API key saved. Run 'circuit capture snap' to capture a bank page.")


@capture.command("snap")
@click.option("--account", "account_id", default=None, help="Account or card ID to import into.")
@click.option("--type", "entity_type", type=click.Choice(["account", "card"]), default=None, help="Entity type.")
@pass_context
def capture_snap(ctx: CircuitContext, account_id: str | None, entity_type: str | None) -> None:
    """Screenshot a bank page, extract transactions, and import."""
    from circuitai.services.capture_service import CaptureService

    db = ctx.get_db()
    svc = CaptureService(db)

    if not svc.is_configured():
        ctx.formatter.error("Anthropic API key not configured. Run 'circuit capture setup' first.")
        return

    # Interactive account selection if not provided
    if not account_id:
        accounts = db.fetchall("SELECT id, name, institution FROM accounts WHERE is_active = 1")
        cards = db.fetchall("SELECT id, name, institution FROM cards WHERE is_active = 1")

        if not accounts and not cards:
            ctx.formatter.error("No accounts or cards found. Add one first with 'circuit accounts add' or 'circuit cards add'.")
            return

        choices: list[tuple[str, str, str]] = []
        for a in accounts:
            choices.append((a["id"], f"{a['name']} ({a['institution']})", "account"))
        for c in cards:
            choices.append((c["id"], f"{c['name']} ({c['institution']})", "card"))

        if not ctx.json_mode:
            ctx.formatter.print("\n[bold]Select an account or card:[/bold]")
            for i, (_, label, etype) in enumerate(choices, 1):
                tag = "[cyan]acct[/cyan]" if etype == "account" else "[yellow]card[/yellow]"
                ctx.formatter.print(f"  {i}. {tag} {label}")

        selection = click.prompt("Number", type=int) - 1
        if selection < 0 or selection >= len(choices):
            ctx.formatter.error("Invalid selection.")
            return

        account_id = choices[selection][0]
        entity_type = choices[selection][2]

    if not entity_type:
        entity_type = "account"

    if not ctx.json_mode:
        ctx.formatter.info("Select the browser window to capture...")

    try:
        result = svc.snap(account_id, entity_type)
    except Exception as e:
        if ctx.json_mode:
            ctx.formatter.json_error(str(e))
        else:
            ctx.formatter.error(str(e))
        return

    if ctx.json_mode:
        ctx.formatter.json(result)
        return

    ctx.formatter.success(
        f"Imported {result['imported']} transactions, "
        f"skipped {result['skipped']} duplicates, "
        f"linked {result.get('linked', 0)} to bills."
    )
    if result.get("balance_updated"):
        ctx.formatter.info("Balance updated.")
    for err in result.get("errors", [])[:5]:
        ctx.formatter.warning(f"  {err}")


@capture.command("status")
@pass_context
def capture_status(ctx: CircuitContext) -> None:
    """Show capture configuration status."""
    from circuitai.services.capture_service import CaptureService, HAS_ANTHROPIC

    db = ctx.get_db()
    svc = CaptureService(db)

    status = {
        "anthropic_package": HAS_ANTHROPIC,
        "api_key_configured": svc.is_configured(),
    }

    if ctx.json_mode:
        ctx.formatter.json(status)
        return

    ctx.formatter.print("\n[bold cyan]Capture Status[/bold cyan]")
    if not HAS_ANTHROPIC:
        ctx.formatter.warning("anthropic package not installed. Install with: pip install circuitai[capture]")
    elif not svc.is_configured():
        ctx.formatter.warning("API key not configured. Run 'circuit capture setup'.")
    else:
        ctx.formatter.success("Capture is configured and ready.")
