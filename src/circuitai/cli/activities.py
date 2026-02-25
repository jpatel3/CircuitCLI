"""Kids activities management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import dollars, format_date


@click.group(cls=JsonGroup)
@pass_context
def activities(ctx: CircuitContext) -> None:
    """Manage kids' activities and sports."""
    pass


@activities.command("list")
@pass_context
def activities_list(ctx: CircuitContext) -> None:
    """List all activities."""
    from circuitai.services.activity_service import ActivityService

    db = ctx.get_db()
    svc = ActivityService(db)
    act_list = svc.list_activities()

    if ctx.json_mode:
        ctx.formatter.json([a.model_dump() for a in act_list])
        return

    if not act_list:
        ctx.formatter.info("No activities found. Use 'circuit activities add' to add one.")
        return

    rows = []
    for a in act_list:
        child_name = "—"
        if a.child_id:
            try:
                child = svc.get_child(a.child_id)
                child_name = child.name
            except Exception:
                pass
        rows.append([a.name, a.sport_or_type, child_name, a.schedule or "—", dollars(a.cost_cents)])

    ctx.formatter.table(
        title="Activities",
        columns=[("Name", "bold"), ("Sport", ""), ("Child", "cyan"), ("Schedule", "dim"), ("Cost", "green")],
        rows=rows,
    )


@activities.command("add")
@click.option("--name", required=True)
@click.option("--child", "child_name", default=None, help="Child's name.")
@click.option("--sport", default="", help="Sport or activity type.")
@click.option("--provider", default="")
@click.option("--season", default="")
@click.option("--cost", type=float, default=0, help="Cost in dollars.")
@click.option("--frequency", default="")
@click.option("--schedule", default="", help="e.g. 'Mon/Wed 5-6pm'")
@click.option("--location", default="")
@pass_context
def activities_add(ctx: CircuitContext, name, child_name, sport, provider, season, cost, frequency, schedule, location) -> None:
    """Add a new activity."""
    from circuitai.services.activity_service import ActivityService

    db = ctx.get_db()
    svc = ActivityService(db)

    child_id = None
    if child_name:
        child = svc.find_child(child_name)
        if child:
            child_id = child.id
        else:
            ctx.formatter.warning(f"Child '{child_name}' not found. Adding activity without child link.")

    activity = svc.add_activity(
        name=name, child_id=child_id, sport_or_type=sport or name,
        provider=provider, season=season, cost_cents=int(cost * 100),
        frequency=frequency, schedule=schedule, location=location,
    )

    if ctx.json_mode:
        ctx.formatter.json(activity.model_dump())
    else:
        ctx.formatter.success(f"Added activity: {activity.name}")


@activities.command("show")
@click.argument("activity_id")
@pass_context
def activities_show(ctx: CircuitContext, activity_id: str) -> None:
    """Show activity details."""
    from circuitai.services.activity_service import ActivityService

    db = ctx.get_db()
    svc = ActivityService(db)
    act = svc.get_activity(activity_id)
    payments = svc.get_payments(activity_id)

    if ctx.json_mode:
        ctx.formatter.json({"activity": act.model_dump(), "payments": [p.model_dump() for p in payments]})
        return

    ctx.formatter.print(f"\n[bold]{act.name}[/bold]")
    ctx.formatter.print(f"  Sport: {act.sport_or_type}")
    if act.child_id:
        try:
            child = svc.get_child(act.child_id)
            ctx.formatter.print(f"  Child: {child.name}")
        except Exception:
            pass
    ctx.formatter.print(f"  Schedule: {act.schedule or '—'}")
    ctx.formatter.print(f"  Location: {act.location or '—'}")
    ctx.formatter.print(f"  Cost: {dollars(act.cost_cents)}")

    if payments:
        ctx.formatter.print("\n  [bold]Payments:[/bold]")
        for p in payments:
            ctx.formatter.print(f"    {format_date(p.paid_date)} — {dollars(p.amount_cents)} {p.description}")


@activities.command("pay")
@click.argument("activity_id")
@click.option("--amount", type=float, required=True)
@click.option("--date", "paid_date", default=None)
@click.option("--description", default="")
@pass_context
def activities_pay(ctx: CircuitContext, activity_id, amount, paid_date, description) -> None:
    """Record a payment for an activity."""
    from circuitai.services.activity_service import ActivityService

    db = ctx.get_db()
    svc = ActivityService(db)
    payment = svc.pay_activity(activity_id, int(amount * 100), paid_date=paid_date, description=description)

    if ctx.json_mode:
        ctx.formatter.json(payment.model_dump())
    else:
        ctx.formatter.success(f"Recorded payment: {dollars(payment.amount_cents)}")


@activities.command("schedule")
@pass_context
def activities_schedule(ctx: CircuitContext) -> None:
    """Show the weekly activity schedule."""
    from circuitai.services.activity_service import ActivityService

    db = ctx.get_db()
    svc = ActivityService(db)
    act_list = svc.list_activities()

    if ctx.json_mode:
        ctx.formatter.json([{"name": a.name, "child_id": a.child_id, "schedule": a.schedule, "location": a.location} for a in act_list if a.schedule])
        return

    scheduled = [a for a in act_list if a.schedule]
    if not scheduled:
        ctx.formatter.info("No scheduled activities.")
        return

    ctx.formatter.print("\n[bold cyan]Weekly Schedule[/bold cyan]")
    for a in scheduled:
        child_name = "—"
        if a.child_id:
            try:
                child = svc.get_child(a.child_id)
                child_name = child.name
            except Exception:
                pass
        location = f" at {a.location}" if a.location else ""
        ctx.formatter.print(f"  {a.schedule} — {a.name} ({child_name}){location}")


@activities.command("costs")
@pass_context
def activities_costs(ctx: CircuitContext) -> None:
    """Show cost summary by child."""
    from circuitai.services.activity_service import ActivityService

    db = ctx.get_db()
    svc = ActivityService(db)
    summary = svc.get_cost_summary()

    if ctx.json_mode:
        ctx.formatter.json(summary)
        return

    ctx.formatter.print("\n[bold cyan]Activity Costs[/bold cyan]")
    for child_data in summary["children"]:
        ctx.formatter.print(f"\n  [bold]{child_data['name']}[/bold] — Total: {dollars(child_data['total_cents'])}")
        for act in child_data["activities"]:
            ctx.formatter.print(f"    {act['name']} ({act['sport']}): {dollars(act['cost_cents'])}")
    ctx.formatter.print(f"\n  [bold]Grand Total: {dollars(summary['total_cents'])}[/bold]")


@activities.command("children")
@pass_context
def activities_children(ctx: CircuitContext) -> None:
    """List all children."""
    from circuitai.services.activity_service import ActivityService

    db = ctx.get_db()
    svc = ActivityService(db)
    children = svc.list_children()

    if ctx.json_mode:
        ctx.formatter.json([c.model_dump() for c in children])
        return

    if not children:
        ctx.formatter.info("No children registered. They'll be added during setup or via activities.")
        return

    for c in children:
        ctx.formatter.print(f"  {c.name} (ID: {c.id})")
