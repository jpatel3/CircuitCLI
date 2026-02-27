"""Morning catchup CLI command."""

from __future__ import annotations

from datetime import date

import click
from rich.console import Console

from circuitai.cli.main import CircuitContext, pass_context
from circuitai.output.formatter import dollars, format_date

console = Console()


@click.command()
@pass_context
def morning(ctx: CircuitContext) -> None:
    """Morning catchup — what needs your attention today."""
    from circuitai.services.morning_service import MorningService

    db = ctx.get_db()
    svc = MorningService(db)
    briefing = svc.get_briefing()

    if ctx.json_mode:
        ctx.formatter.json(briefing)
        return

    today = date.today()
    console.print()
    console.print(f"[bold]Good morning![/bold] {today.strftime('%A, %b %d, %Y')}")
    console.print()

    # Attention items
    items = briefing["attention_items"]
    if items:
        console.print(f"[bold red]NEEDS ATTENTION ({len(items)} items)[/bold red]")
        for item in items:
            if item["type"] == "bill_due":
                days = item["days_until"]
                if days == 0:
                    when = "due TODAY"
                elif days == 1:
                    when = "due tomorrow"
                else:
                    when = f"due in {days} days ({format_date(item['due_date'])})"
                console.print(f"  [red][!][/red] {item['title']} — {dollars(item['amount_cents'])} {when}")
            elif item["type"] in ("deadline_upcoming", "deadline_overdue"):
                if item.get("days_until") and item["days_until"] < 0:
                    console.print(f"  [red][!][/red] {item['title']} — OVERDUE ({format_date(item['due_date'])})")
                else:
                    console.print(f"  [yellow][!][/yellow] {item['title']} — due {format_date(item['due_date'])}")
            elif item["type"] == "subscription_charge":
                days = item["days_until"]
                when = "charging TODAY" if days == 0 else f"in {days} days"
                console.print(f"  [yellow][!][/yellow] {item['title']} — {dollars(item['amount_cents'])} {when}")
            elif item["type"] == "lab_unreviewed":
                flagged = item.get("flagged_count", 0)
                flag_msg = f" ({flagged} flagged)" if flagged else ""
                console.print(f"  [cyan][+][/cyan] {item['title']}{flag_msg} — needs review")
        console.print()

    else:
        console.print("[green]All clear — no urgent items![/green]\n")

    # This week
    week = briefing["week_summary"]
    console.print("[bold cyan]THIS WEEK[/bold cyan]")
    console.print(f"  {dollars(week['bills_due_cents'])} in bills due ({week['bills_due_count']} bills)")
    console.print(f"  {week['deadlines_count']} deadlines upcoming")
    flagged_markers = week.get("health_flagged_markers", 0)
    if flagged_markers:
        console.print(f"  [red]{flagged_markers} flagged lab markers[/red]")
    console.print()

    # Accounts snapshot
    accts = briefing["accounts_snapshot"]
    cards = briefing["cards_snapshot"]
    if accts or cards:
        console.print("[bold cyan]ACCOUNTS SNAPSHOT[/bold cyan]")
        parts = []
        for a in accts:
            parts.append(f"{a['name']}: {dollars(a['balance_cents'])}")
        for c in cards:
            parts.append(f"{c['name']}: {dollars(c['balance_cents'])} / {dollars(c['limit_cents'])}")
        # Print in pairs
        for i in range(0, len(parts), 2):
            line = "  " + parts[i]
            if i + 1 < len(parts):
                line += "  |  " + parts[i + 1]
            console.print(line)
