"""Interactive REPL — prompt_toolkit-based session with slash commands and natural text."""

from __future__ import annotations

import shlex

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel

from circuitai.cli.main import CircuitContext
from circuitai.core.config import get_history_path, load_config
from circuitai.core.encryption import MasterKeyManager
from circuitai.services.undo_service import UndoService

console = Console()

# Slash commands available in the REPL
SLASH_COMMANDS = [
    "/bills", "/accounts", "/cards", "/mortgage", "/investments",
    "/deadlines", "/activities", "/morning", "/dashboard",
    "/calendar", "/adapters", "/export", "/sync",
    "/settings", "/help", "/quit", "/exit", "/undo",
    "/query",
]

QUESTION_STARTERS = {"what", "when", "where", "how", "which", "who", "show", "is", "are", "do", "does", "can", "will"}
ACTION_STARTERS = {"paid", "pay", "add", "mark", "cancel", "delete", "remove", "complete", "undo"}


def _unlock_db(ctx: CircuitContext) -> bool:
    """Prompt for master password and set up the database connection."""
    config = load_config()
    from circuitai.core.config import get_data_dir
    data_dir = get_data_dir(config)
    key_mgr = MasterKeyManager(data_dir)

    if not key_mgr.is_initialized:
        console.print("[yellow]No database found. Run [bold]circuit setup[/bold] first.[/yellow]")
        return False

    password = click.prompt("Master password", hide_input=True, err=True)
    try:
        key = key_mgr.unlock(password)
        ctx.set_key(key)
        return True
    except Exception as e:
        ctx.formatter.error(f"Unlock failed: {e}")
        return False


def _show_help() -> None:
    """Display REPL help."""
    help_text = (
        "[bold cyan]COMMANDS[/bold cyan]\n"
        "  /bills        — Manage bills (list, add, show, pay, edit, delete)\n"
        "  /accounts     — Manage bank accounts\n"
        "  /cards        — Manage credit cards\n"
        "  /mortgage     — Mortgage tracking\n"
        "  /investments  — Investment accounts\n"
        "  /deadlines    — Deadline tracking\n"
        "  /activities   — Kids activities\n"
        "  /morning      — Morning briefing\n"
        "  /calendar     — Calendar sync\n"
        "  /adapters     — Adapter management\n"
        "  /export       — Export data\n"
        "  /dashboard    — Launch full TUI dashboard\n"
        "  /help         — This help message\n"
        "  /quit         — Exit\n"
        "\n"
        "[bold cyan]Or just type naturally:[/bold cyan]\n"
        '  Questions: "what bills are due this week?"\n'
        '  Add entries: "hockey registration $350 for Jake"\n'
        '  Mark paid: "paid electric bill $142"'
    )
    console.print(Panel(help_text, title="CircuitAI Help", border_style="cyan"))


def _route_slash_command(ctx: CircuitContext, command: str) -> None:
    """Route a slash command to the appropriate Click command."""
    parts = command.lstrip("/").split(None, 1)
    cmd_name = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    if cmd_name in ("quit", "exit"):
        raise EOFError()

    if cmd_name == "help":
        _show_help()
        return

    if cmd_name == "undo":
        undo_svc = getattr(ctx, "_undo_svc", None)
        if undo_svc and undo_svc.has_undo:
            result = undo_svc.undo()
            ctx.formatter.success(result)
        else:
            ctx.formatter.info("Nothing to undo.")
        return

    if cmd_name == "morning":
        cmd_name = "morning"

    # Find the Click command in the CLI group
    from circuitai.cli.main import cli as cli_group

    click_cmd = cli_group.commands.get(cmd_name)
    if click_cmd is None:
        ctx.formatter.error(f"Unknown command: /{cmd_name}. Type /help for available commands.")
        return

    # Build args list
    args = shlex.split(rest) if rest else []
    if isinstance(click_cmd, click.Group) and not args:
        args = ["list"]  # Default subcommand for groups

    try:
        # Create a new Click context and invoke
        with click.Context(click_cmd, parent=None, info_name=cmd_name) as sub_ctx:
            sub_ctx.ensure_object(CircuitContext)
            sub_ctx.obj = ctx
            click_cmd.parse_args(sub_ctx, args)
            click_cmd.invoke(sub_ctx)
    except SystemExit:
        pass
    except click.UsageError as e:
        ctx.formatter.error(str(e))
    except Exception as e:
        ctx.formatter.error(f"Error: {e}")


def _route_natural_text(ctx: CircuitContext, text: str) -> None:
    """Route natural language text to the appropriate service."""
    text_lower = text.lower().strip()
    first_word = text_lower.split()[0] if text_lower else ""

    # Question → QueryService
    if first_word in QUESTION_STARTERS or text_lower.endswith("?"):
        try:
            from circuitai.services.query_service import QueryService
            db = ctx.get_db()
            svc = QueryService(db)
            result = svc.query(text)
            ctx.formatter.print(result)
        except Exception as e:
            ctx.formatter.error(f"Query failed: {e}")
        return

    # Action keywords → TextParser
    if first_word in ACTION_STARTERS:
        try:
            from circuitai.services.text_parser import TextParser
            db = ctx.get_db()
            parser = TextParser(db)
            result = parser.parse_and_execute(text)
            ctx.formatter.success(result)
        except Exception as e:
            ctx.formatter.error(f"Parse failed: {e}")
        return

    # Ambiguous → try TextParser, confirm with user
    try:
        from circuitai.services.text_parser import TextParser
        db = ctx.get_db()
        parser = TextParser(db)
        parsed = parser.parse(text)
        if parsed and parsed.get("confidence", 0) > 0.6:
            desc = parser.describe(parsed)
            if click.confirm(f"→ {desc}. Correct?", default=True):
                result = parser.execute(parsed)
                ctx.formatter.success(result)
            return
    except Exception:
        pass

    ctx.formatter.warning(
        f'Not sure what to do with "{text}". Try /help for commands or phrase as a question.'
    )


def launch_repl(ctx: CircuitContext) -> None:
    """Launch the interactive REPL session."""
    console.print()
    console.print(
        Panel(
            "[bold cyan]CircuitAI[/bold cyan] — Personal Finance CLI\n"
            "Type naturally or use /commands. Type [bold]/help[/bold] for help.",
            border_style="cyan",
        )
    )
    console.print()

    # Unlock database
    if not _unlock_db(ctx):
        return

    # Ensure schema is current
    try:
        db = ctx.get_db()
        from circuitai.core.migrations import initialize_database
        initialize_database(db)
    except Exception as e:
        ctx.formatter.error(f"Database error: {e}")
        return

    # Attach undo service
    ctx._undo_svc = UndoService(db)

    ctx.formatter.success("Database unlocked. Ready!")
    console.print()

    # Set up prompt session with completion and history
    completer = WordCompleter(SLASH_COMMANDS, sentence=True)
    history = FileHistory(str(get_history_path()))
    session: PromptSession[str] = PromptSession(
        completer=completer,
        history=history,
        enable_history_search=True,
    )

    while True:
        try:
            text = session.prompt("circuit> ").strip()
            if not text:
                continue

            if text.startswith("/"):
                _route_slash_command(ctx, text)
            elif text.lower() in ("morning", "catchup"):
                _route_slash_command(ctx, "/morning")
            elif text.lower() == "undo":
                _route_slash_command(ctx, "/undo")
            else:
                _route_natural_text(ctx, text)

            console.print()  # blank line between outputs

        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]Goodbye![/dim]")
            ctx.close()
            break
