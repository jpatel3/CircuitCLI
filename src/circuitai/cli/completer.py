"""Rich autocompleter for the CircuitAI REPL with descriptions and subcommand support."""

from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document


class CircuitCompleter(Completer):
    """Two-level completer: slash commands with descriptions, then subcommands."""

    def __init__(
        self,
        command_meta: dict[str, str],
        subcommand_meta: dict[str, dict[str, str]],
    ) -> None:
        self._command_meta = command_meta
        self._subcommand_meta = subcommand_meta

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> list[Completion]:
        text = document.text_before_cursor.lstrip()

        # Level 2: subcommand completion after "/<command> "
        if text.startswith("/") and " " in text:
            cmd_part, sub_part = text.split(None, 1) if len(text.split()) > 1 else (text.rstrip(), "")
            cmd_name = cmd_part.lstrip("/")
            subs = self._subcommand_meta.get(cmd_name, {})
            if subs:
                for name, desc in subs.items():
                    if name.startswith(sub_part):
                        yield Completion(
                            name,
                            start_position=-len(sub_part),
                            display_meta=desc,
                        )
            return

        # Level 1: slash command completion
        if text.startswith("/"):
            prefix = text
            for cmd, desc in self._command_meta.items():
                if cmd.startswith(prefix):
                    yield Completion(
                        cmd,
                        start_position=-len(prefix),
                        display_meta=desc,
                    )
            return

        # No completions for non-slash text
        return
