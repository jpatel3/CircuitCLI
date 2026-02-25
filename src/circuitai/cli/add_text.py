"""Free-form text input CLI command."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, pass_context


@click.command("add")
@click.argument("text", nargs=-1, required=True)
@pass_context
def add_cmd(ctx: CircuitContext, text: tuple[str, ...]) -> None:
    """Add an entry from free-form text.

    Examples:
        circuit add "JCPL electric bill $142 due March 15"
        circuit add "paid hockey registration $350 for Jake"
        circuit add "dentist appointment March 20 high priority"
    """
    from circuitai.services.text_parser import TextParser

    full_text = " ".join(text)
    db = ctx.get_db()
    parser = TextParser(db)
    parsed = parser.parse(full_text)

    if ctx.json_mode:
        # In JSON mode, always return the parsed result
        if parsed["confidence"] >= 0.3:
            result = parser.execute(parsed)
            ctx.formatter.json({"parsed": parsed, "result": result})
        else:
            ctx.formatter.json_error(f"Low confidence parse: {parsed}", code=1)
        return

    if parsed["confidence"] < 0.3:
        ctx.formatter.warning(f"Couldn't confidently parse: \"{full_text}\"")
        ctx.formatter.info("Try being more specific, e.g., 'JCPL electric bill $142 due March 15'")
        return

    # Describe what we understood and confirm
    desc = parser.describe(parsed)
    if click.confirm(f"→ {desc}. Correct?", default=True):
        result = parser.execute(parsed)
        ctx.formatter.success(result)
    else:
        ctx.formatter.info("Cancelled. Try rephrasing or use a specific command like /bills add.")
