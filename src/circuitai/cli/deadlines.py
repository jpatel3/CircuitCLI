"""Deadline management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import format_date


@click.group(cls=JsonGroup)
@pass_context
def deadlines(ctx: CircuitContext) -> None:
    """Track deadlines and due dates."""
    pass


@deadlines.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include completed deadlines.")
@pass_context
def deadlines_list(ctx: CircuitContext, show_all: bool) -> None:
    """List all deadlines."""
    from circuitai.services.deadline_service import DeadlineService

    db = ctx.get_db()
    svc = DeadlineService(db)
    dl_list = svc.list_deadlines(active_only=not show_all)

    if ctx.json_mode:
        ctx.formatter.json([d.model_dump() for d in dl_list])
        return

    if not dl_list:
        ctx.formatter.info("No deadlines. Use 'circuit deadlines add' to add one.")
        return

    rows = []
    for d in dl_list:
        days = f"{d.days_until}d" if d.days_until is not None else "—"
        status = "OVERDUE" if d.is_overdue else ("Done" if d.is_completed else days)
        rows.append([d.title, format_date(d.due_date), d.priority, d.category, status])

    ctx.formatter.table(
        title="Deadlines",
        columns=[("Title", "bold"), ("Due", "cyan"), ("Priority", "yellow"), ("Category", "dim"), ("Status", "red")],
        rows=rows,
    )


@deadlines.command("add")
@click.option("--title", required=True)
@click.option("--due-date", required=True, help="Due date (YYYY-MM-DD).")
@click.option("--description", default="")
@click.option("--priority", default="medium", help="Priority: low, medium, high, urgent.")
@click.option("--category", default="general")
@pass_context
def deadlines_add(ctx: CircuitContext, title, due_date, description, priority, category) -> None:
    """Add a new deadline."""
    from circuitai.services.deadline_service import DeadlineService

    db = ctx.get_db()
    svc = DeadlineService(db)
    dl = svc.add_deadline(title=title, due_date=due_date, description=description, priority=priority, category=category)

    if ctx.json_mode:
        ctx.formatter.json(dl.model_dump())
    else:
        ctx.formatter.success(f"Added deadline: {dl.title}, due {format_date(dl.due_date)}")


@deadlines.command("show")
@click.argument("deadline_id")
@pass_context
def deadlines_show(ctx: CircuitContext, deadline_id: str) -> None:
    """Show deadline details."""
    from circuitai.services.deadline_service import DeadlineService

    db = ctx.get_db()
    svc = DeadlineService(db)
    dl = svc.get_deadline(deadline_id)

    if ctx.json_mode:
        ctx.formatter.json(dl.model_dump())
        return

    ctx.formatter.print(f"\n[bold]{dl.title}[/bold]")
    ctx.formatter.print(f"  Due: {format_date(dl.due_date)}")
    ctx.formatter.print(f"  Priority: {dl.priority}")
    ctx.formatter.print(f"  Category: {dl.category}")
    if dl.description:
        ctx.formatter.print(f"  Description: {dl.description}")
    days = dl.days_until
    if days is not None:
        if days < 0:
            ctx.formatter.print(f"  Status: [red]OVERDUE by {abs(days)} days[/red]")
        elif days == 0:
            ctx.formatter.print("  Status: [yellow]Due TODAY[/yellow]")
        else:
            ctx.formatter.print(f"  Status: {days} days remaining")


@deadlines.command("complete")
@click.argument("deadline_id")
@pass_context
def deadlines_complete(ctx: CircuitContext, deadline_id: str) -> None:
    """Mark a deadline as complete."""
    from circuitai.services.deadline_service import DeadlineService

    db = ctx.get_db()
    svc = DeadlineService(db)
    dl = svc.complete_deadline(deadline_id)

    if ctx.json_mode:
        ctx.formatter.json(dl.model_dump())
    else:
        ctx.formatter.success(f"Completed: {dl.title}")


@deadlines.command("edit")
@click.argument("deadline_id")
@click.option("--title", default=None)
@click.option("--due-date", default=None)
@click.option("--priority", default=None)
@click.option("--description", default=None)
@pass_context
def deadlines_edit(ctx: CircuitContext, deadline_id: str, **kwargs) -> None:
    """Edit a deadline."""
    from circuitai.services.deadline_service import DeadlineService

    db = ctx.get_db()
    svc = DeadlineService(db)
    updates = {k.replace("-", "_"): v for k, v in kwargs.items() if v is not None}
    if not updates:
        ctx.formatter.warning("No updates specified.")
        return
    dl = svc.update_deadline(deadline_id, **updates)

    if ctx.json_mode:
        ctx.formatter.json(dl.model_dump())
    else:
        ctx.formatter.success(f"Updated: {dl.title}")


@deadlines.command("delete")
@click.argument("deadline_id")
@pass_context
def deadlines_delete(ctx: CircuitContext, deadline_id: str) -> None:
    """Delete a deadline."""
    from circuitai.services.deadline_service import DeadlineService

    db = ctx.get_db()
    svc = DeadlineService(db)
    svc.delete_deadline(deadline_id)

    if ctx.json_mode:
        ctx.formatter.json({"deleted": deadline_id})
    else:
        ctx.formatter.success("Deadline deleted.")
