"""Interactive REPL — prompt_toolkit-based session with slash commands and natural text."""

from __future__ import annotations

import os
import shlex

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel

from circuitai.cli.completer import CircuitCompleter
from circuitai.cli.main import CircuitContext
from circuitai.core.config import get_history_path, load_config
from circuitai.core.encryption import MasterKeyManager
from circuitai.services.undo_service import UndoService

console = Console()

# Slash commands with descriptions for autocomplete
SLASH_COMMAND_META: dict[str, str] = {
    "/bills": "Manage bills",
    "/accounts": "Manage bank accounts",
    "/cards": "Manage credit cards",
    "/mortgage": "Mortgage tracking",
    "/investments": "Investment accounts",
    "/deadlines": "Track deadlines",
    "/activities": "Kids activities",
    "/morning": "Morning briefing",
    "/dashboard": "Launch TUI dashboard",
    "/calendar": "Calendar sync",
    "/adapters": "Adapter management",
    "/plaid": "Plaid bank sync",
    "/capture": "Screen capture import",
    "/export": "Export data",
    "/sync": "Sync adapters",
    "/settings": "App settings",
    "/query": "Ask a question",
    "/undo": "Undo last action",
    "/help": "Show help",
    "/quit": "Exit REPL",
    "/exit": "Exit REPL",
}

# Subcommands with descriptions, keyed by command name (without slash)
SUBCOMMAND_META: dict[str, dict[str, str]] = {
    "bills": {
        "list": "List all bills",
        "add": "Add a new bill",
        "show": "Show bill details",
        "pay": "Record a payment",
        "edit": "Edit a bill",
        "delete": "Delete a bill",
        "summary": "Bill summary",
        "link": "Auto-match transactions",
        "unmatched": "Show unmatched transactions",
        "confirm-match": "Confirm a transaction match",
    },
    "accounts": {
        "list": "List all accounts",
        "add": "Add a new account",
        "show": "Show account details",
        "update-balance": "Update balance",
        "transactions": "Show transactions",
    },
    "cards": {
        "list": "List all cards",
        "add": "Add a new card",
        "show": "Show card details",
        "update-balance": "Update balance",
        "transactions": "Show transactions",
    },
    "mortgage": {
        "list": "List all mortgages",
        "add": "Add a new mortgage",
        "show": "Show mortgage details",
        "pay": "Record a payment",
        "amortization": "Amortization schedule",
    },
    "investments": {
        "list": "List all accounts",
        "add": "Add a new account",
        "show": "Show account details",
        "contribute": "Record a contribution",
        "performance": "Show performance",
    },
    "deadlines": {
        "list": "List all deadlines",
        "add": "Add a new deadline",
        "show": "Show deadline details",
        "complete": "Mark as complete",
        "edit": "Edit a deadline",
        "delete": "Delete a deadline",
    },
    "activities": {
        "list": "List all activities",
        "add": "Add a new activity",
        "show": "Show activity details",
        "pay": "Record a payment",
        "schedule": "Weekly schedule",
        "costs": "Cost summary by child",
        "children": "List all children",
    },
    "adapters": {
        "list": "List available adapters",
        "info": "Show adapter details",
        "configure": "Configure an adapter",
        "sync": "Sync from an adapter",
    },
    "calendar": {
        "setup": "Configure CalDAV connection",
        "sync": "Trigger calendar sync",
        "status": "Show sync status",
    },
    "plaid": {
        "setup": "Configure Plaid credentials",
        "link": "Connect a bank account",
        "sync": "Sync transactions & balances",
        "status": "Show connected banks",
        "identity": "Fetch account holder info",
    },
    "capture": {
        "setup": "Configure API key",
        "snap": "Screenshot & import",
        "status": "Show capture status",
    },
    "export": {
        "csv": "Export as CSV",
        "json": "Export as JSON",
    },
}

# Flat list for backward compat in _show_help()
SLASH_COMMANDS = list(SLASH_COMMAND_META.keys())

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
        # Pick a sensible default subcommand
        if "list" in click_cmd.commands:
            args = ["list"]
        elif "status" in click_cmd.commands:
            args = ["status"]
        elif not getattr(click_cmd, "invoke_without_command", False):
            # No safe default — show available subcommands
            subs = ", ".join(sorted(click_cmd.commands.keys()))
            ctx.formatter.info(f"Available subcommands: {subs}")
            return

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


def _pick_account(db) -> str | None:
    """Show numbered account/card list and return selected ID, or None if cancelled."""
    accounts = db.fetchall("SELECT id, name, institution FROM accounts WHERE is_active = 1")
    cards = db.fetchall("SELECT id, name, institution FROM cards WHERE is_active = 1")

    if not accounts and not cards:
        return None

    choices: list[tuple[str, str]] = []
    for a in accounts:
        choices.append((a["id"], f"[cyan]acct[/cyan] {a['name']} ({a['institution']})"))
    for c in cards:
        choices.append((c["id"], f"[yellow]card[/yellow] {c['name']} ({c['institution']})"))

    console.print("\n[bold]Select an account:[/bold]")
    for i, (_, label) in enumerate(choices, 1):
        console.print(f"  {i}. {label}")

    selection = click.prompt("Number", type=int) - 1
    if selection < 0 or selection >= len(choices):
        return None
    return choices[selection][0]


def _handle_file_import(ctx: CircuitContext, file_path: str) -> None:
    """Handle a detected file drop — prompt user and route to the appropriate importer."""
    from circuitai.services.file_import_service import get_file_type, import_file

    file_type = get_file_type(file_path)
    basename = os.path.basename(file_path)
    console.print(f"[cyan]Detected {file_type.upper()} file:[/cyan] {basename}")

    if not click.confirm("Import this file?", default=True):
        return

    try:
        db = ctx.get_db()

        if file_type == "csv":
            account_id = _pick_account(db)
            if not account_id:
                ctx.formatter.error("No accounts found. Add one first with '/accounts add'.")
                return
            result = import_file(db, file_path, account_id)
            ctx.formatter.success(
                f"Imported {result['imported']} transactions, linked {result.get('linked', 0)}."
            )
            if result.get("errors"):
                for err in result["errors"][:5]:
                    ctx.formatter.warning(f"  {err}")

        elif file_type == "pdf":
            mode = click.prompt(
                "Mode",
                type=click.Choice(["transactions", "bill-info"]),
                default="bill-info",
            )

            if mode == "transactions":
                account_id = _pick_account(db)
                if not account_id:
                    ctx.formatter.error("No accounts found. Add one first with '/accounts add'.")
                    return
                result = import_file(db, file_path, account_id, mode=mode)
                ctx.formatter.success(f"Imported {result['imported']} transactions.")
                if result.get("errors"):
                    for err in result["errors"][:5]:
                        ctx.formatter.warning(f"  {err}")
            else:
                result = import_file(db, file_path, account_id="", mode=mode)
                amount = result.get("amount_due")
                due = result.get("due_date")
                if amount is not None:
                    console.print(f"  [bold]Amount due:[/bold] ${amount / 100:.2f}")
                if due:
                    console.print(f"  [bold]Due date:[/bold]  {due}")
                if amount is None and due is None:
                    ctx.formatter.warning("Could not extract bill info from this PDF.")
                elif click.confirm("Create a bill from this?", default=False):
                    bill_name = click.prompt("Bill name")
                    from circuitai.services.bill_service import BillService
                    svc = BillService(db)
                    svc.add_bill(name=bill_name, amount_cents=amount or 0, due_date=due or "")
                    ctx.formatter.success(f"Bill '{bill_name}' created.")

    except Exception as e:
        ctx.formatter.error(f"Import failed: {e}")


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
    completer = CircuitCompleter(SLASH_COMMAND_META, SUBCOMMAND_META)
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

            # Check for file path BEFORE slash command routing
            # (dragged paths like /Users/foo/file.pdf start with /)
            from circuitai.services.file_import_service import looks_like_file_path

            detected_path = looks_like_file_path(text)
            if detected_path:
                _handle_file_import(ctx, detected_path)
            elif text.startswith("/"):
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
