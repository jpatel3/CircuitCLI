"""Calendar sync CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context


@click.group(cls=JsonGroup)
@pass_context
def calendar(ctx: CircuitContext) -> None:
    """CalDAV calendar sync management."""
    pass


@calendar.command("setup")
@pass_context
def calendar_setup(ctx: CircuitContext) -> None:
    """Configure CalDAV calendar connection."""
    from circuitai.core.config import update_config

    if ctx.json_mode:
        ctx.formatter.json_error("Calendar setup requires interactive mode.", code=1)
        return

    ctx.formatter.print("\n[bold cyan]Calendar Setup[/bold cyan]")
    ctx.formatter.print("Configure CalDAV sync (Apple Calendar, Google, Nextcloud, etc.)\n")

    server_url = click.prompt("CalDAV server URL", default="https://caldav.icloud.com")
    username = click.prompt("Username")
    password = click.prompt("Password", hide_input=True)
    calendar_name = click.prompt("Calendar name", default="CircuitAI")

    # Save config (non-sensitive)
    update_config(calendar={
        "enabled": True,
        "server_url": server_url,
        "username": username,
        "calendar_name": calendar_name,
    })

    # Store credentials in encrypted DB
    import json
    db = ctx.get_db()
    creds = json.dumps({"username": username, "password": password})
    db.execute(
        """INSERT OR REPLACE INTO adapter_state (id, adapter_name, key, value)
           VALUES (?, 'calendar', 'credentials', ?)""",
        (f"calendar-creds", creds),
    )
    db.commit()

    ctx.formatter.success("Calendar configured.")

    # Test connection
    try:
        from circuitai.services.calendar_service import CalendarService
        cal_svc = CalendarService(db)
        cal_svc.connect()
        ctx.formatter.success("Connection test passed.")
    except Exception as e:
        ctx.formatter.warning(f"Connection test failed: {e}")
        ctx.formatter.info("You can fix this later and retry with 'circuit calendar status'.")


@calendar.command("sync")
@pass_context
def calendar_sync(ctx: CircuitContext) -> None:
    """Trigger a manual calendar sync."""
    from circuitai.services.calendar_service import CalendarService

    db = ctx.get_db()
    svc = CalendarService(db)
    results = svc.sync()

    if ctx.json_mode:
        ctx.formatter.json(results)
        return

    if results["status"] == "success":
        ctx.formatter.success(f"Sync complete. Pushed: {results['pushed']}, Pulled: {results['pulled']}")
    elif results["status"] == "skipped":
        ctx.formatter.info(f"Sync skipped: {results['reason']}")
    else:
        for err in results.get("errors", []):
            ctx.formatter.error(err)


@calendar.command("status")
@pass_context
def calendar_status(ctx: CircuitContext) -> None:
    """Show calendar sync status."""
    from circuitai.services.calendar_service import CalendarService

    db = ctx.get_db()
    svc = CalendarService(db)
    status = svc.get_status()

    if ctx.json_mode:
        ctx.formatter.json(status)
        return

    ctx.formatter.print("\n[bold cyan]Calendar Status[/bold cyan]")
    ctx.formatter.print(f"  Status: {status['status']}")
    if status["status"] == "configured":
        ctx.formatter.print(f"  Server: {status['server_url']}")
        ctx.formatter.print(f"  Calendar: {status['calendar_name']}")
        ctx.formatter.print(f"  Last sync: {status.get('last_sync') or 'Never'}")
        ctx.formatter.print(f"  Synced items: {status['synced_items']}")
    elif "reason" in status:
        ctx.formatter.print(f"  Reason: {status['reason']}")
