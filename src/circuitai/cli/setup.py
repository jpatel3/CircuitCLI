"""First-run setup wizard — creates encrypted DB and initial configuration."""

from __future__ import annotations

import click
from rich.console import Console
from rich.panel import Panel

from circuitai.cli.main import CircuitContext, pass_context
from circuitai.core.config import get_data_dir, load_config, update_config
from circuitai.core.database import DatabaseConnection
from circuitai.core.encryption import MasterKeyManager
from circuitai.core.migrations import initialize_database

console = Console()


@click.command("setup")
@pass_context
def setup_cmd(ctx: CircuitContext) -> None:
    """Run the first-time setup wizard."""
    fmt = ctx.formatter
    config = load_config()

    console.print()
    console.print(
        Panel(
            "[bold cyan]Welcome to CircuitAI![/bold cyan]\n\n"
            "Local-first, privacy-focused personal finance CLI.\n"
            "All your data stays on this machine in an encrypted database.",
            border_style="cyan",
        )
    )
    console.print()

    # Step 1: Data directory
    data_dir = get_data_dir(config)
    console.print(f"[dim]Data directory:[/dim] {data_dir}")

    # Step 2: Master password
    key_mgr = MasterKeyManager(data_dir)

    if key_mgr.is_initialized:
        console.print("[yellow]Database already initialized.[/yellow]")
        password = click.prompt("Enter your master password", hide_input=True)
        try:
            key = key_mgr.unlock(password)
            fmt.success("Database unlocked.")
        except Exception as e:
            fmt.error(str(e))
            raise SystemExit(1)
    else:
        console.print("\n[bold]Set a master password[/bold] to encrypt your database.")
        console.print("[dim]This password is never stored — don't forget it![/dim]\n")

        while True:
            password = click.prompt("Master password", hide_input=True)
            confirm = click.prompt("Confirm password", hide_input=True)
            if password == confirm:
                break
            fmt.error("Passwords don't match. Try again.")

        key = key_mgr.initialize(password)
        fmt.success("Master password set and encryption keys created.")

    # Step 3: Initialize database schema
    db = DatabaseConnection(db_path=data_dir / "circuitai.db", encryption_key=key)
    db.connect()
    try:
        version = initialize_database(db)
        fmt.success(f"Database schema initialized (v{version}).")
    finally:
        db.close()

    # Step 4: Mark first_run = False
    update_config(general={"first_run": False})
    fmt.success("Configuration saved.")

    console.print()
    console.print(
        Panel(
            "[bold green]Setup complete![/bold green]\n\n"
            "Next steps:\n"
            "  • [cyan]circuit[/cyan] — Launch interactive REPL\n"
            "  • [cyan]circuit bills add[/cyan] — Add your first bill\n"
            "  • [cyan]circuit accounts add[/cyan] — Add a bank account\n"
            "  • [cyan]circuit --help[/cyan] — See all commands",
            border_style="green",
        )
    )
