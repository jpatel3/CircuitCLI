"""CLI command to launch the CircuitAI web dashboard."""

from __future__ import annotations

import click
from rich.console import Console

from circuitai.cli.main import CircuitContext, pass_context

console = Console()


@click.command("serve")
@click.option("--port", default=8321, show_default=True, help="Port to serve on.")
@click.option("--host", default="127.0.0.1", show_default=True, help="Host to bind to.")
@click.option("--no-browser", is_flag=True, help="Don't auto-open browser.")
@pass_context
def serve(ctx: CircuitContext, port: int, host: str, no_browser: bool) -> None:
    """Launch the web dashboard at http://127.0.0.1:PORT."""
    try:
        import uvicorn
        from circuitai.web.app import create_app
    except ImportError:
        ctx.formatter.error(
            "Web dependencies not installed. Run:\n"
            "  pip install circuitai[web]"
        )
        raise SystemExit(1)

    # Derive encryption key from master password
    from circuitai.core.config import get_data_dir
    from circuitai.core.encryption import MasterKeyManager

    data_dir = get_data_dir()
    key_mgr = MasterKeyManager(data_dir)

    encryption_key = None
    if key_mgr.is_initialized:
        password = click.prompt("Master password", hide_input=True)
        try:
            encryption_key = key_mgr.unlock(password)
            ctx.formatter.success("Database unlocked.")
        except Exception as e:
            ctx.formatter.error(f"Failed to unlock: {e}")
            raise SystemExit(1)

    app = create_app(encryption_key=encryption_key)
    url = f"http://{host}:{port}"

    console.print(f"\n[bold cyan]CircuitAI Web Dashboard[/bold cyan]")
    console.print(f"  [dim]Serving at[/dim] {url}")
    console.print(f"  [dim]Press Ctrl+C to stop[/dim]\n")

    if not no_browser:
        import threading
        import time
        import webbrowser

        def _open_browser():
            time.sleep(1)
            webbrowser.open(url)

        threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
