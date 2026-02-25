# CircuitAI

Local-first, privacy-focused personal finance and productivity CLI.

All data stays on your machine in an encrypted SQLite database. Agent-native design with `--json` mode for AI agents and a rich terminal experience for humans.

## Quick Start

```bash
pip install -e .
circuit setup    # Set master password, initialize encrypted DB
circuit          # Launch interactive REPL
circuit --help   # See all commands
```

## Features

- **Interactive REPL** — type naturally or use `/commands`
- **Morning Catchup** — `circuit morning` for a daily briefing
- **Bill Tracking** — recurring bills with payment history
- **Bank Accounts & Credit Cards** — balance tracking and transactions
- **Mortgage** — amortization schedule and payments
- **Investments** — brokerage, 401(k), 529, IRA tracking
- **Deadlines** — priority-based deadline management
- **Kids Activities** — per-child, per-sport cost tracking
- **Textual Dashboard** — full TUI with `circuit dashboard`
- **CalDAV Calendar Sync** — two-way sync with Apple Calendar, Google, etc.
- **Plugin System** — extensible via `entry_points` adapters
- **Export** — CSV and JSON export for all data
- **Agent-Native** — every command supports `--json` for AI agents
