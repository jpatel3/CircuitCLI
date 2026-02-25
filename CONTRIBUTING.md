# Contributing to CircuitAI

CircuitAI uses a plugin-based adapter system for external data sources. This guide covers how to add a new integration.

## Adding a New Adapter

### 1. Copy the Template

```bash
cp src/circuitai/adapters/builtin/_template.py src/circuitai/adapters/builtin/my_source.py
```

### 2. Implement the Protocol

Every adapter must implement these 5 methods:

| Method | Purpose | Required |
|--------|---------|----------|
| `metadata()` | Return name, version, description, author | Yes |
| `configure()` | Interactive setup (prompts for credentials) | Optional |
| `validate_config()` | Check if configuration is valid | Optional |
| `sync(db)` | Fetch + import data into the database | Yes |
| `test_connection()` | Verify connectivity without syncing | Optional |

The `BaseAdapter` class (`src/circuitai/adapters/base.py`) provides sensible defaults for the optional methods. You only need to implement `metadata()` and `sync()` at minimum.

### 3. Register the Entry Point

Add your adapter to `pyproject.toml`:

```toml
[project.entry-points."circuitai.adapters"]
manual = "circuitai.adapters.builtin.manual:ManualAdapter"
csv-import = "circuitai.adapters.builtin.csv_import:CsvImportAdapter"
my-source = "circuitai.adapters.builtin.my_source:MySourceAdapter"  # ← add this
```

Then reinstall:

```bash
pip install -e .
```

Verify with:

```bash
circuit integrations        # should show your adapter
circuit adapters info my-source
```

### Example Adapters

| Adapter | Complexity | File |
|---------|-----------|------|
| Manual | Minimal (no-op sync) | `src/circuitai/adapters/builtin/manual.py` |
| CSV Import | Full (interactive config, parsing, statement linking) | `src/circuitai/adapters/builtin/csv_import.py` |

### External Adapters

Adapters don't have to live in this repo. Any installed Python package can register a `circuitai.adapters` entry point and it will be discovered automatically. This means you can:

- Publish your adapter as a separate PyPI package
- Keep proprietary integrations private
- Distribute adapters independently of CircuitAI releases

## Development Setup

```bash
# Clone and install in dev mode
git clone https://github.com/jpatel3/CircuitCLI.git
cd CircuitCLI
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check src/ tests/
```

## Code Style

- Python 3.11+, type hints throughout
- `from __future__ import annotations` in every module
- Pydantic models with `to_row()`/`from_row()` for DB serialization
- All monetary amounts stored as **integer cents**
- All IDs are UUID strings
- Services layer between CLI and repositories
- `OutputFormatter` for dual-mode output (Rich for humans, JSON for agents)

## Project Layout

```
src/circuitai/
├── adapters/          # Plugin system (protocol, base, registry, built-ins)
├── cli/               # Click command groups
├── core/              # Database, config, migrations, exceptions
├── models/            # Pydantic models + repositories
├── output/            # OutputFormatter (Rich + JSON)
└── services/          # Business logic layer
tests/                 # pytest test suite
```
