"""Subscription management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context
from circuitai.output.formatter import dollars, format_date


@click.group(cls=JsonGroup)
@pass_context
def subscriptions(ctx: CircuitContext) -> None:
    """Manage subscriptions (list, detect, add, show, cancel, summary)."""
    pass


@subscriptions.command("list")
@click.option("--all", "show_all", is_flag=True, help="Include inactive/cancelled subscriptions.")
@pass_context
def subscriptions_list(ctx: CircuitContext, show_all: bool) -> None:
    """List all subscriptions."""
    from circuitai.services.subscription_service import SubscriptionService

    db = ctx.get_db()
    svc = SubscriptionService(db)
    sub_list = svc.list_subscriptions(active_only=not show_all)

    if ctx.json_mode:
        ctx.formatter.json([s.model_dump() for s in sub_list])
        return

    if not sub_list:
        ctx.formatter.info(
            "No subscriptions found. Run detection or add one manually:\n\n"
            "  /subscriptions detect   — Auto-detect from transactions\n"
            "  /subscriptions add      — Add manually"
        )
        return

    rows = []
    for s in sub_list:
        confidence_str = f"{s.confidence}%"
        rows.append([
            s.name,
            dollars(s.amount_cents),
            s.frequency,
            format_date(s.next_charge_date),
            s.status,
            confidence_str,
        ])

    ctx.formatter.table(
        title="Subscriptions",
        columns=[
            ("Name", "bold"),
            ("Amount", "green"),
            ("Frequency", ""),
            ("Next Charge", "cyan"),
            ("Status", "yellow"),
            ("Confidence", "dim"),
        ],
        rows=rows,
    )


@subscriptions.command("detect")
@pass_context
def subscriptions_detect(ctx: CircuitContext) -> None:
    """Detect recurring charges from transaction history."""
    from circuitai.services.subscription_service import SubscriptionService

    db = ctx.get_db()
    svc = SubscriptionService(db)
    detected = svc.detect_subscriptions()

    if ctx.json_mode:
        ctx.formatter.json([s.model_dump() for s in detected])
        return

    if not detected:
        ctx.formatter.info(
            "No new subscriptions detected. Import more transactions for better detection."
        )
        return

    ctx.formatter.print(f"\n[bold cyan]Detected {len(detected)} potential subscriptions:[/bold cyan]\n")

    rows = []
    for i, s in enumerate(detected, 1):
        # Color code confidence
        conf = s.confidence
        if conf >= 80:
            conf_style = f"[green]{conf}%[/green]"
        elif conf >= 60:
            conf_style = f"[yellow]{conf}%[/yellow]"
        else:
            conf_style = f"[dim]{conf}%[/dim]"

        rows.append([
            str(i),
            s.name,
            dollars(s.amount_cents),
            s.frequency,
            format_date(s.next_charge_date),
            conf_style,
        ])

    ctx.formatter.table(
        title="Detected Subscriptions",
        columns=[
            ("#", "dim"),
            ("Name", "bold"),
            ("Amount", "green"),
            ("Frequency", ""),
            ("Next Charge", "cyan"),
            ("Confidence", ""),
        ],
        rows=rows,
    )

    # Prompt for confirmation
    choice = click.prompt(
        "\nConfirm all (a), select individually (s), or skip (n)?",
        type=click.Choice(["a", "s", "n"]),
        default="a",
    )

    if choice == "n":
        ctx.formatter.info("Skipped all.")
        return

    if choice == "a":
        count = svc.confirm_detected(detected)
        total_monthly = sum(s.monthly_cost_cents for s in detected)
        ctx.formatter.success(
            f"Confirmed {count} subscriptions ({dollars(total_monthly)}/mo)."
        )
        return

    # Individual selection
    confirmed = []
    skipped = 0
    for s in detected:
        if click.confirm(f"  Confirm {s.name} ({dollars(s.amount_cents)}/{s.frequency})?", default=True):
            confirmed.append(s)
        else:
            skipped += 1

    if confirmed:
        count = svc.confirm_detected(confirmed)
        total_monthly = sum(s.monthly_cost_cents for s in confirmed)
        ctx.formatter.success(
            f"Confirmed {count} subscriptions ({dollars(total_monthly)}/mo), skipped {skipped}."
        )
    else:
        ctx.formatter.info("No subscriptions confirmed.")


@subscriptions.command("add")
@click.option("--name", prompt="Subscription name", help="Subscription name.")
@click.option("--amount", type=float, prompt="Amount in dollars", default=0, help="Amount in dollars.")
@click.option("--frequency", prompt="Frequency (weekly/monthly/quarterly/yearly)", default="monthly", help="Billing frequency.")
@click.option("--category", default="other", help="Category.")
@click.option("--notes", default="", help="Notes.")
@pass_context
def subscriptions_add(
    ctx: CircuitContext,
    name: str,
    amount: float,
    frequency: str,
    category: str,
    notes: str,
) -> None:
    """Add a subscription manually."""
    from circuitai.services.subscription_service import SubscriptionService

    db = ctx.get_db()
    svc = SubscriptionService(db)
    sub = svc.add_subscription(
        name=name,
        amount_cents=int(amount * 100),
        frequency=frequency,
        category=category,
        notes=notes,
    )

    if ctx.json_mode:
        ctx.formatter.json(sub.model_dump())
    else:
        ctx.formatter.success(f"Added subscription: {sub.name}, {dollars(sub.amount_cents)}/{sub.frequency}")


@subscriptions.command("show")
@click.argument("sub_id", required=False)
@pass_context
def subscriptions_show(ctx: CircuitContext, sub_id: str | None) -> None:
    """Show details for a subscription."""
    from circuitai.services.subscription_service import SubscriptionService

    db = ctx.get_db()
    svc = SubscriptionService(db)

    if not sub_id:
        # Numbered picker
        subs = svc.list_subscriptions()
        if not subs:
            ctx.formatter.info("No subscriptions found.")
            return
        ctx.formatter.print("\n[bold]Select a subscription:[/bold]")
        for i, s in enumerate(subs, 1):
            ctx.formatter.print(f"  {i}. {s.name} ({dollars(s.amount_cents)}/{s.frequency})")
        choice = click.prompt("Number", type=int) - 1
        if choice < 0 or choice >= len(subs):
            ctx.formatter.error("Invalid selection.")
            return
        sub = subs[choice]
    else:
        sub = svc.get_subscription(sub_id)

    if ctx.json_mode:
        ctx.formatter.json(sub.model_dump())
        return

    ctx.formatter.print(f"\n[bold]{sub.name}[/bold]")
    ctx.formatter.print(f"  Provider: {sub.provider}")
    ctx.formatter.print(f"  Amount: {dollars(sub.amount_cents)}/{sub.frequency}")
    ctx.formatter.print(f"  Monthly cost: {dollars(sub.monthly_cost_cents)}")
    ctx.formatter.print(f"  Yearly cost: {dollars(sub.yearly_cost_cents)}")
    ctx.formatter.print(f"  Category: {sub.category}")
    ctx.formatter.print(f"  Status: {sub.status}")
    ctx.formatter.print(f"  Next charge: {format_date(sub.next_charge_date)}")
    ctx.formatter.print(f"  Last charge: {format_date(sub.last_charge_date)}")
    ctx.formatter.print(f"  Confidence: {sub.confidence}%")
    ctx.formatter.print(f"  Source: {sub.source}")
    ctx.formatter.print(f"  ID: {sub.id}")
    if sub.notes:
        ctx.formatter.print(f"  Notes: {sub.notes}")


@subscriptions.command("cancel")
@click.argument("sub_id", required=False)
@pass_context
def subscriptions_cancel(ctx: CircuitContext, sub_id: str | None) -> None:
    """Cancel a subscription."""
    from circuitai.services.subscription_service import SubscriptionService

    db = ctx.get_db()
    svc = SubscriptionService(db)

    if not sub_id:
        # Numbered picker of active subs
        subs = [s for s in svc.list_subscriptions() if s.status == "active"]
        if not subs:
            ctx.formatter.info("No active subscriptions to cancel.")
            return
        ctx.formatter.print("\n[bold]Select a subscription to cancel:[/bold]")
        for i, s in enumerate(subs, 1):
            ctx.formatter.print(f"  {i}. {s.name} ({dollars(s.amount_cents)}/{s.frequency})")
        choice = click.prompt("Number", type=int) - 1
        if choice < 0 or choice >= len(subs):
            ctx.formatter.error("Invalid selection.")
            return
        sub = subs[choice]
    else:
        sub = svc.get_subscription(sub_id)

    if not ctx.json_mode:
        if not click.confirm(f"Cancel subscription '{sub.name}'?"):
            ctx.formatter.info("Cancelled.")
            return

    svc.cancel_subscription(sub.id)

    if ctx.json_mode:
        ctx.formatter.json({"cancelled": sub.id})
    else:
        ctx.formatter.success(f"Cancelled subscription: {sub.name}")


@subscriptions.command("summary")
@pass_context
def subscriptions_summary(ctx: CircuitContext) -> None:
    """Show subscription cost breakdown."""
    from circuitai.services.subscription_service import SubscriptionService

    db = ctx.get_db()
    svc = SubscriptionService(db)
    summary = svc.get_summary()

    if ctx.json_mode:
        ctx.formatter.json(summary)
        return

    ctx.formatter.print("\n[bold cyan]Subscription Summary[/bold cyan]")
    ctx.formatter.print(f"  Active subscriptions: {summary['total_active']}")
    ctx.formatter.print(f"  Monthly total: {dollars(summary['monthly_total_cents'])}")
    ctx.formatter.print(f"  Yearly total: {dollars(summary['yearly_total_cents'])}")
    ctx.formatter.print(f"  Upcoming (7 days): {summary['upcoming_count']}")

    if summary["by_category"]:
        ctx.formatter.print("\n  [bold]By Category (monthly):[/bold]")
        for cat, cents in sorted(summary["by_category"].items(), key=lambda x: -x[1]):
            ctx.formatter.print(f"    {cat}: {dollars(cents)}")

    if summary["by_frequency"]:
        ctx.formatter.print("\n  [bold]By Frequency:[/bold]")
        for freq, count in sorted(summary["by_frequency"].items()):
            ctx.formatter.print(f"    {freq}: {count}")
