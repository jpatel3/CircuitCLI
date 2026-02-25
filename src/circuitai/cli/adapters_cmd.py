"""Adapter/plugin management CLI commands."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, pass_context


@click.group()
@pass_context
def adapters(ctx: CircuitContext) -> None:
    """Manage data adapters and plugins."""
    pass


@adapters.command("list")
@pass_context
def adapters_list(ctx: CircuitContext) -> None:
    """List available adapters."""
    from circuitai.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    available = registry.list_adapters()

    if ctx.json_mode:
        ctx.formatter.json(available)
        return

    if not available:
        ctx.formatter.info("No adapters found.")
        return

    ctx.formatter.print("\n[bold cyan]Available Adapters[/bold cyan]")
    for adapter in available:
        ctx.formatter.print(f"  {adapter['name']} — {adapter['description']}")
        ctx.formatter.print(f"    Version: {adapter.get('version', '—')}")


@adapters.command("info")
@click.argument("adapter_name")
@pass_context
def adapters_info(ctx: CircuitContext, adapter_name: str) -> None:
    """Show details about an adapter."""
    from circuitai.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    try:
        info = registry.get_adapter_info(adapter_name)
        if ctx.json_mode:
            ctx.formatter.json(info)
        else:
            ctx.formatter.print(f"\n[bold]{info['name']}[/bold]")
            ctx.formatter.print(f"  {info['description']}")
            ctx.formatter.print(f"  Version: {info.get('version', '—')}")
    except Exception as e:
        ctx.formatter.error(str(e))


@adapters.command("configure")
@click.argument("adapter_name")
@pass_context
def adapters_configure(ctx: CircuitContext, adapter_name: str) -> None:
    """Configure an adapter."""
    from circuitai.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    try:
        adapter = registry.load_adapter(adapter_name)
        adapter.configure()
        ctx.formatter.success(f"Adapter '{adapter_name}' configured.")
    except Exception as e:
        ctx.formatter.error(str(e))


@adapters.command("sync")
@click.argument("adapter_name", required=False, default=None)
@pass_context
def adapters_sync(ctx: CircuitContext, adapter_name: str | None) -> None:
    """Sync data from an adapter (or all adapters)."""
    from circuitai.adapters.registry import AdapterRegistry

    registry = AdapterRegistry()
    db = ctx.get_db()

    if adapter_name:
        names = [adapter_name]
    else:
        names = [a["name"] for a in registry.list_adapters()]

    results = {}
    for name in names:
        try:
            adapter = registry.load_adapter(name)
            result = adapter.sync(db)
            results[name] = {"status": "success", "result": result}
            if not ctx.json_mode:
                ctx.formatter.success(f"Synced: {name}")
        except Exception as e:
            results[name] = {"status": "error", "error": str(e)}
            if not ctx.json_mode:
                ctx.formatter.error(f"Sync failed for {name}: {e}")

    if ctx.json_mode:
        ctx.formatter.json(results)
