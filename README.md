# CircuitAI

**Local-first, privacy-focused personal finance and productivity CLI.**

All data stays on your machine in an encrypted SQLite database. Agent-native design with `--json` mode for AI agents and a rich terminal experience for humans.

## Quick Start

```bash
# Install
pip install -e .

# Initialize (set master password, create encrypted DB)
circuit setup

# Launch the interactive REPL
circuit

# Or use commands directly
circuit --help
```

## Features

- **Interactive REPL** — type naturally or use `/commands` with tab completion and history
- **Morning Catchup** — `circuit morning` for a daily financial briefing
- **Bill Tracking** — recurring bills with payment history, due-date alerts, and auto-matching
- **Bank Accounts** — balance tracking, transaction import, and statement linking
- **Credit Cards** — balance, limit, utilization tracking
- **Mortgage** — amortization schedule, payments, and equity tracking
- **Investments** — brokerage, 401(k), 529, IRA portfolio tracking
- **Deadlines** — priority-based deadline management with calendar sync
- **Kids Activities** — per-child, per-sport cost and schedule tracking
- **Natural Language Input** — `circuit add "paid electric bill $142"` parses and records
- **Natural Language Queries** — `circuit query "what bills are due this week?"`
- **Textual Dashboard** — full TUI with `circuit dashboard`
- **CalDAV Calendar Sync** — two-way sync with Apple Calendar, Google Calendar, etc.
- **Plugin System** — extensible via Python entry-point adapters
- **CSV Import** — import bank/card statements from CSV files
- **Export** — CSV and JSON export for all data types
- **Undo** — revert the last destructive operation
- **Agent-Native** — every command supports `--json` for AI agent consumption

## Command Reference

| Command | Description |
|---------|-------------|
| `circuit` | Launch interactive REPL |
| `circuit setup` | Initialize database and master password |
| `circuit morning` | Daily briefing — bills due, deadlines, activity schedule |
| `circuit bills` | Manage recurring bills (list, add, pay, show, edit, summary) |
| `circuit accounts` | Bank accounts (list, add, show, update-balance, transactions) |
| `circuit cards` | Credit cards (list, add, show, update-balance) |
| `circuit mortgage` | Mortgage tracking (show, payment, schedule) |
| `circuit investments` | Investment accounts (list, add, show, update) |
| `circuit deadlines` | Deadline management (list, add, show, complete) |
| `circuit activities` | Kids activities (list, add, show, log-cost) |
| `circuit add <text>` | Parse natural language into a structured entry |
| `circuit query <text>` | Ask questions about your finances |
| `circuit dashboard` | Launch the Textual TUI dashboard |
| `circuit calendar` | CalDAV calendar sync (setup, sync, status) |
| `circuit adapters` | Manage data adapters (list, info, configure, sync) |
| `circuit integrations` | View all integrations and their status |
| `circuit export` | Export data to CSV or JSON |
| `circuit seed` | Load demo data for testing |

Every command supports `--json` for structured output:

```bash
circuit --json bills list
circuit bills --json summary
```

## Interactive REPL

Launch with `circuit` (no subcommand). The REPL supports slash commands and natural language:

```
circuit> /bills list
circuit> /morning
circuit> paid electric bill $142
circuit> what bills are due this week?
circuit> /undo
circuit> /quit
```

Tab completion and persistent history are built in.

## Morning Catchup

```bash
circuit morning
```

Shows a daily briefing with:
- Bills due soon (next 7 days)
- Upcoming deadlines
- Today's activity schedule
- Account balance summary

## JSON / Agent-Native Mode

Every command wraps output in a `{"status": "success", "data": ...}` envelope:

```bash
$ circuit --json bills list
{
  "status": "success",
  "data": [
    {
      "id": "abc-123",
      "name": "Electric",
      "amount_cents": 14200,
      "due_day": 15,
      "frequency": "monthly"
    }
  ]
}
```

Errors return `{"status": "error", "error": {"message": "...", "code": 1}}`.

This makes CircuitAI a natural backend for AI agents and automation scripts.

## Integrations & Plugin System

View all integrations (adapters + built-in services):

```bash
circuit integrations
circuit integrations list --kind adapter
circuit integrations info calendar-sync
```

### Built-in Services

| Integration | Description |
|-------------|-------------|
| `calendar-sync` | Two-way CalDAV sync for bills, deadlines, and activities |
| `statement-linker` | Auto-match imported transactions to known bills |
| `text-parser` | Convert natural language to structured financial entries |
| `query-engine` | Answer natural language questions about your data |

### Adapter Plugins

CircuitAI discovers adapters via Python entry points. Built-in adapters:

| Adapter | Description |
|---------|-------------|
| `manual` | Manual data entry via CLI commands |
| `csv-import` | Import transactions from CSV bank/card statements |

Anyone can create and publish an adapter as a standalone Python package. See [CONTRIBUTING.md](CONTRIBUTING.md) for the 3-step process.

## CalDAV Calendar Sync

Sync bills, deadlines, and activities to any CalDAV server (Apple Calendar, Google, Nextcloud, etc.):

```bash
pip install -e ".[calendar]"   # install caldav dependency
circuit calendar setup         # configure server URL + credentials
circuit calendar sync          # push/pull events
circuit calendar status        # check sync status
```

## Encryption

CircuitAI uses SQLCipher for at-rest encryption. Your data never leaves your machine.

```bash
pip install -e ".[crypto]"     # install sqlcipher dependency
circuit setup                  # set master password
```

Without SQLCipher installed, CircuitAI falls back to plain SQLite (still local-only).

## Tech Stack

- **Python 3.11+** — type hints throughout
- **Click** — CLI framework with nested command groups
- **Rich** — tables, panels, and styled terminal output
- **Textual** — full TUI dashboard
- **Pydantic** — data validation and serialization
- **prompt_toolkit** — REPL with history and completion
- **SQLite / SQLCipher** — local encrypted storage
- **CalDAV** — optional calendar sync

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new adapters, set up the dev environment, and follow code conventions.

## License

MIT
