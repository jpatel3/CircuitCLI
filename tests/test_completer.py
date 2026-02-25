"""Tests for the CircuitAI REPL autocompleter."""

from __future__ import annotations

from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document

from circuitai.cli.completer import CircuitCompleter

COMMANDS = {
    "/bills": "Manage bills",
    "/accounts": "Manage bank accounts",
    "/help": "Show help",
    "/quit": "Exit REPL",
}

SUBCOMMANDS = {
    "bills": {
        "list": "List all bills",
        "add": "Add a new bill",
        "pay": "Record a payment",
    },
    "accounts": {
        "list": "List all accounts",
        "add": "Add a new account",
    },
}


def _get_completions(completer: CircuitCompleter, text: str) -> list[tuple[str, str]]:
    """Helper: return [(completion_text, display_meta_text), ...] for given input text."""
    doc = Document(text, len(text))
    event = CompleteEvent()
    return [(c.text, c.display_meta_text) for c in completer.get_completions(doc, event)]


def test_slash_shows_all_commands():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/")
    texts = [r[0] for r in results]
    assert "/bills" in texts
    assert "/accounts" in texts
    assert "/help" in texts
    assert "/quit" in texts
    assert len(results) == 4


def test_slash_commands_have_descriptions():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/")
    meta_map = {r[0]: r[1] for r in results}
    assert meta_map["/bills"] == "Manage bills"
    assert meta_map["/accounts"] == "Manage bank accounts"


def test_partial_match_filters():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/bi")
    texts = [r[0] for r in results]
    assert "/bills" in texts
    assert "/accounts" not in texts


def test_partial_match_no_results():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/xyz")
    assert results == []


def test_subcommand_completion_after_space():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/bills ")
    texts = [r[0] for r in results]
    assert "list" in texts
    assert "add" in texts
    assert "pay" in texts
    assert len(results) == 3


def test_subcommand_descriptions():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/bills ")
    meta_map = {r[0]: r[1] for r in results}
    assert meta_map["list"] == "List all bills"
    assert meta_map["pay"] == "Record a payment"


def test_subcommand_partial_match():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/bills li")
    texts = [r[0] for r in results]
    assert texts == ["list"]


def test_no_subcommands_for_simple_command():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/help ")
    assert results == []


def test_no_subcommands_for_quit():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/quit ")
    assert results == []


def test_no_completion_for_plain_text():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "what bills are due")
    assert results == []


def test_accounts_subcommands():
    completer = CircuitCompleter(COMMANDS, SUBCOMMANDS)
    results = _get_completions(completer, "/accounts ")
    texts = [r[0] for r in results]
    assert "list" in texts
    assert "add" in texts
    assert len(results) == 2
