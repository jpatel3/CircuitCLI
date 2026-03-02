# CircuitAI

[![CI](https://github.com/jpatel3/CircuitCLI/actions/workflows/ci.yml/badge.svg)](https://github.com/jpatel3/CircuitCLI/actions)

**Your Personal Command Center — local-first, privacy-focused.**

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
- **Web Dashboard** — browser-based UI with `circuit serve` (Health, Subscriptions, more coming)
- **Morning Catchup** — `circuit morning` for a daily financial briefing
- **Bill Tracking** — recurring bills with payment history, due-date alerts, and auto-matching
- **Subscription Tracking** — auto-detect recurring charges from transactions, manage manually, cost breakdowns by category
- **Health Dashboard** — lab results, flagged markers, marker trends over time
- **Bank Accounts** — balance tracking, transaction import, and statement linking
- **Credit Cards** — balance, limit, utilization tracking
- **Mortgage** — amortization schedule, payments, and equity tracking
- **Investments** — brokerage, 401(k), 529, IRA portfolio tracking
- **Deadlines** — priority-based deadline management with calendar sync
- **Kids Activities** — per-child, per-sport cost and schedule tracking
- **Browser Automation** — `circuit browse` for syncing data from utility portals (JCPL, etc.)
- **Natural Language Input** — `circuit add "paid electric bill $142"` parses and records
- **Natural Language Queries** — `circuit query "what bills are due this week?"`, `"show my account balances"`, `"what's my net worth?"`
- **Textual Dashboard** — full TUI with `circuit dashboard`
- **CalDAV Calendar Sync** — two-way sync with Apple Calendar, Google Calendar, etc.
- **Plugin System** — extensible via Python entry-point adapters
- **CSV Import** — import bank/card statements from CSV files
- **Export** — CSV and JSON export for all data types
- **Undo** — revert the last destructive operation (supports add, pay, complete, delete, and update across all entity types: bills, accounts, cards, deadlines, activities, investments, mortgages)
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
| `circuit subscriptions` | Subscription tracking (list, add, detect, show, cancel, summary) |
| `circuit health` | Health tracking (import-lab, results, markers, trends) |
| `circuit serve` | Launch the web dashboard (browser UI) |
| `circuit browse` | Browser automation for utility portals (setup, sync, status) |
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

### Slash Commands

All 18 slash commands: `/bills`, `/accounts`, `/cards`, `/mortgage`, `/investments`, `/deadlines`, `/activities`, `/morning`, `/dashboard`, `/calendar`, `/adapters`, `/export`, `/sync`, `/settings`, `/help`, `/undo`, `/query`, `/quit`

### Natural Language

The REPL detects natural language automatically:
- **Questions** — `what bills are due this week?`, `show my account balances`, `what's my net worth?`
- **Actions** — keywords like `paid`, `add`, and `complete` are recognized with confidence scoring
- **Fallback** — unrecognized input is passed to the query engine

Word completion and persistent history file are built in.

## TUI Dashboard

Launch with `circuit dashboard` or `/dashboard` in the REPL.

The dashboard displays 7 panels: financial summary, bills, accounts, cards, deadlines, investments, and activities. Click or press Enter on any panel to drill down into a detail screen.

**Keyboard shortcuts:**

| Key | Action |
|-----|--------|
| `q` / `Escape` | Quit |
| `r` | Refresh |
| `Tab` / `Shift+Tab` | Navigate between panels |

## Web Dashboard

Launch the browser-based dashboard:

```bash
circuit serve              # starts at http://localhost:8000
circuit serve --port 9000  # custom port
```

Login with your master password. The web UI provides:

- **Health Dashboard** — lab results, flagged markers with dates, marker trend charts, search
- **Subscriptions Dashboard** — active count, monthly/yearly cost cards, subscription table, category doughnut chart, add/detect/cancel flows

All pages support HTMX live search and partial refresh without full page reloads.

### CLI + Web Parity

The CLI and web dashboard share the same service layer and database. Any data added via one interface is immediately visible in the other.

| Action | CLI | Web |
|--------|-----|-----|
| List subscriptions | `circuit subscriptions list` | `/subscriptions` |
| Add subscription | `circuit subscriptions add` | `/subscriptions/add` |
| Detect from transactions | `circuit subscriptions detect` | `/subscriptions/detect` |
| Subscription detail | `circuit subscriptions show` | `/subscriptions/{id}` |
| Cancel subscription | `circuit subscriptions cancel` | Detail page button |
| Cost summary | `circuit subscriptions summary` | Dashboard summary cards |
| View lab results | `circuit health results` | `/health` |
| Marker trends | `circuit health trends` | `/health/trends/{marker}` |

## Morning Catchup

```bash
circuit morning
```

Shows a daily briefing with:
- **Attention items** sorted by urgency — overdue deadlines, bills due today, upcoming deadlines
- **Bills due** in the next 7 days (smart filtering skips recently-paid bills within 25 days)
- **Today's activity schedule**
- **Accounts and cards snapshot** — balances and utilization

## Seed Data

Load demo data for testing or exploration:

```bash
circuit seed --profile demo      # full demo dataset
circuit seed --profile minimal   # minimal starter data
```

The `demo` profile populates: 4 bank accounts, 3 credit cards, 10 bills, 1 mortgage, 6 investments, 2 children, 4 activities, and 2 deadlines.

## Export

Export your data to CSV or JSON:

```bash
circuit export csv --entity bills
circuit export json --entity all
circuit export csv --entity accounts -o accounts.csv
```

Supported entity types: `bills`, `accounts`, `cards`, `investments`, `deadlines`, `activities` (plus `all` for JSON export). Use `-o <file>` to write to a file instead of stdout.

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
- **FastAPI + Jinja2 + HTMX** — web dashboard with Pico CSS
- **Pydantic** — data validation and serialization
- **prompt_toolkit** — REPL with history and completion
- **SQLite / SQLCipher** — local encrypted storage
- **Playwright** — optional browser automation for utility portals
- **CalDAV** — optional calendar sync

## Testing & CI

```bash
python -m pytest               # run all tests
python -m pytest -x            # stop on first failure
```

428 tests across 18 test files covering CLI commands, services, repositories, web dashboard, browser automation, and adapters. GitHub Actions CI runs on Python 3.11 and 3.12 with Ruff linting, pytest, and build verification.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add new adapters, set up the dev environment, and follow code conventions.

## License

MIT
