"""Integrations overview CLI command — shows all adapters + built-in services."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, JsonGroup, pass_context


@click.group(cls=JsonGroup, invoke_without_command=True)
@pass_context
def integrations(ctx: CircuitContext) -> None:
    """View available integrations and their status."""
    if click.get_current_context().invoked_subcommand is None:
        # Default: show all integrations
        _show_list(ctx, kind="all")


@integrations.command("list")
@click.option(
    "--kind",
    type=click.Choice(["adapter", "builtin", "all"]),
    default="all",
    help="Filter by integration kind.",
)
@pass_context
def integrations_list(ctx: CircuitContext, kind: str) -> None:
    """List integrations, optionally filtered by kind."""
    _show_list(ctx, kind=kind)


@integrations.command("info")
@click.argument("name")
@pass_context
def integrations_info(ctx: CircuitContext, name: str) -> None:
    """Show detailed information about a specific integration."""
    from circuitai.services.integration_registry import IntegrationRegistry

    db = _safe_db(ctx)
    registry = IntegrationRegistry(db=db)
    info = registry.get(name)

    if info is None:
        if ctx.json_mode:
            ctx.formatter.json_error(f"Integration not found: {name}")
        else:
            ctx.formatter.error(f"Integration not found: {name}")
        return

    if ctx.json_mode:
        ctx.formatter.json(info.to_dict())
        return

    status_color = _status_color(info.status.value)
    ctx.formatter.print(f"\n[bold]{info.name}[/bold]")
    ctx.formatter.print(f"  Kind:    {info.kind}")
    ctx.formatter.print(f"  Desc:    {info.description}")
    ctx.formatter.print(f"  Version: {info.version}")
    ctx.formatter.print(f"  Status:  [{status_color}]{info.status.value}[/{status_color}]")
    if info.status_detail:
        ctx.formatter.print(f"  Detail:  {info.status_detail}")
    if info.requires:
        ctx.formatter.print(f"  Requires: {', '.join(info.requires)}")
    if info.config_command:
        ctx.formatter.print(f"  Config:  {info.config_command}")
    ctx.formatter.print()


def _show_list(ctx: CircuitContext, kind: str) -> None:
    """Shared helper for listing integrations."""
    from circuitai.services.integration_registry import IntegrationRegistry

    db = _safe_db(ctx)
    registry = IntegrationRegistry(db=db)
    all_integrations = registry.list_all()

    if kind != "all":
        all_integrations = [i for i in all_integrations if i.kind == kind]

    if ctx.json_mode:
        ctx.formatter.json([i.to_dict() for i in all_integrations])
        return

    if not all_integrations:
        ctx.formatter.info("No integrations found.")
        return

    rows = []
    for i in all_integrations:
        status_color = _status_color(i.status.value)
        rows.append([
            i.name,
            i.kind,
            i.description,
            f"[{status_color}]{i.status.value}[/{status_color}]",
        ])

    ctx.formatter.table(
        title="Integrations",
        columns=[
            ("Name", "bold"),
            ("Kind", "dim"),
            ("Description", ""),
            ("Status", ""),
        ],
        rows=rows,
        data_for_json=[i.to_dict() for i in all_integrations],
    )


def _safe_db(ctx: CircuitContext):
    """Get DB connection or None if unavailable (no password set)."""
    try:
        return ctx.get_db()
    except Exception:
        return None


def _status_color(status: str) -> str:
    """Map status to a Rich color."""
    return {
        "active": "green",
        "configured": "cyan",
        "available": "yellow",
        "unavailable": "dim",
        "error": "red",
    }.get(status, "")
