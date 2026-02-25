"""Integration tests for CLI commands using Click's CliRunner."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from circuitai.cli.main import CircuitContext, cli
from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database


@pytest.fixture
def tmp_db():
    """Create a temporary database with full schema for CLI tests."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_cli.db"
        db = DatabaseConnection(db_path=db_path)
        db.connect()
        initialize_database(db)
        yield db
        db.close()


@pytest.fixture
def cli_runner(tmp_db):
    """Return a CliRunner that patches CircuitContext.get_db to use the temp DB.

    This ensures every CLI command that calls ctx.get_db() receives our
    pre-initialized temporary database instead of the real one.
    """
    runner = CliRunner()

    def patched_get_db(self):
        # Always return the test database
        self._db = tmp_db
        return tmp_db

    with patch.object(CircuitContext, "get_db", patched_get_db):
        yield runner


class TestRootCLI:
    """Tests for the root `circuit` command."""

    def test_help(self, cli_runner):
        """circuit --help shows usage info and subcommands."""
        result = cli_runner.invoke(cli, ["--help"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "CircuitAI" in result.output
        assert "bills" in result.output
        assert "accounts" in result.output
        assert "deadlines" in result.output
        assert "seed" in result.output

    def test_version(self, cli_runner):
        """circuit --version prints the version string."""
        result = cli_runner.invoke(cli, ["--version"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "CircuitAI" in result.output
        assert "0.1.0" in result.output


class TestBillsCLI:
    """Tests for the `circuit bills` subcommand group."""

    def test_bills_help(self, cli_runner):
        """circuit bills --help shows bill subcommands."""
        result = cli_runner.invoke(cli, ["bills", "--help"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "list" in result.output
        assert "add" in result.output
        assert "pay" in result.output
        assert "summary" in result.output

    def test_bills_list_json_empty(self, cli_runner):
        """circuit bills list --json returns valid JSON with an empty list."""
        result = cli_runner.invoke(
            cli, ["--json", "bills", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"] == []

    def test_bills_add_json(self, cli_runner):
        """circuit bills add --json creates a bill and returns JSON."""
        result = cli_runner.invoke(
            cli,
            [
                "--json", "bills", "add",
                "--name", "Test Electric",
                "--provider", "TestCo",
                "--amount", "142.00",
                "--due-day", "15",
                "--frequency", "monthly",
                "--category", "electricity",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"]["name"] == "Test Electric"
        assert data["data"]["amount_cents"] == 14200

    def test_bills_list_after_add(self, cli_runner):
        """After adding a bill, bills list returns it."""
        # Add a bill first
        cli_runner.invoke(
            cli,
            [
                "--json", "bills", "add",
                "--name", "Water Bill",
                "--provider", "Water Co",
                "--amount", "67.50",
                "--due-day", "20",
            ],
            catch_exceptions=False,
        )

        # List should contain the bill
        result = cli_runner.invoke(
            cli, ["--json", "bills", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert len(data["data"]) >= 1
        names = [b["name"] for b in data["data"]]
        assert "Water Bill" in names


class TestSeedCLI:
    """Tests for the `circuit seed` command."""

    def test_seed_demo_json(self, cli_runner):
        """circuit seed --yes --profile demo --json populates data and returns counts."""
        result = cli_runner.invoke(
            cli,
            ["--json", "seed", "--yes", "--profile", "demo"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"]["profile"] == "demo"

        counts = data["data"]["counts"]
        assert counts["bills"] == 10
        assert counts["accounts"] == 4
        assert counts["cards"] == 3
        assert counts["mortgages"] == 1
        assert counts["investments"] == 6
        assert counts["children"] == 2
        assert counts["activities"] == 4
        assert counts["deadlines"] == 2

    def test_bills_populated_after_seed(self, cli_runner):
        """After seeding, circuit bills list --json returns populated data."""
        # Seed first
        cli_runner.invoke(
            cli,
            ["--json", "seed", "--yes", "--profile", "demo"],
            catch_exceptions=False,
        )

        # Now list bills
        result = cli_runner.invoke(
            cli, ["--json", "bills", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert len(data["data"]) == 10
        bill_names = [b["name"] for b in data["data"]]
        assert "JCPL Electric" in bill_names
        assert "Xfinity Internet" in bill_names

    def test_seed_minimal_json(self, cli_runner):
        """circuit seed --yes --profile minimal --json returns empty counts."""
        result = cli_runner.invoke(
            cli,
            ["--json", "seed", "--yes", "--profile", "minimal"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"]["profile"] == "minimal"
        assert data["data"]["counts"] == {}


class TestAccountsCLI:
    """Tests for the `circuit accounts` subcommand group."""

    def test_accounts_help(self, cli_runner):
        """circuit accounts --help shows account subcommands."""
        result = cli_runner.invoke(
            cli, ["accounts", "--help"], catch_exceptions=False
        )
        assert result.exit_code == 0
        assert "list" in result.output
        assert "add" in result.output

    def test_accounts_list_json_empty(self, cli_runner):
        """circuit accounts list --json returns valid JSON with an empty list."""
        result = cli_runner.invoke(
            cli, ["--json", "accounts", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"] == []

    def test_accounts_list_after_seed(self, cli_runner):
        """After seeding, circuit accounts list --json returns 4 accounts."""
        cli_runner.invoke(
            cli,
            ["--json", "seed", "--yes", "--profile", "demo"],
            catch_exceptions=False,
        )

        result = cli_runner.invoke(
            cli, ["--json", "accounts", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert len(data["data"]) == 4
        names = [a["name"] for a in data["data"]]
        assert "Chase Checking" in names
        assert "Wealthfront Cash" in names


class TestDeadlinesCLI:
    """Tests for the `circuit deadlines` subcommand group."""

    def test_deadlines_help(self, cli_runner):
        """circuit deadlines --help shows deadline subcommands."""
        result = cli_runner.invoke(
            cli, ["deadlines", "--help"], catch_exceptions=False
        )
        assert result.exit_code == 0
        assert "list" in result.output
        assert "add" in result.output
        assert "complete" in result.output

    def test_deadlines_list_json_empty(self, cli_runner):
        """circuit deadlines list --json returns valid JSON with an empty list."""
        result = cli_runner.invoke(
            cli, ["--json", "deadlines", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"] == []

    def test_deadlines_list_after_seed(self, cli_runner):
        """After seeding, circuit deadlines list --json returns seeded deadlines.

        The seed creates 2 explicit deadlines, plus the bill service may
        auto-create deadlines from bill due dates, so we check at least 2.
        """
        cli_runner.invoke(
            cli,
            ["--json", "seed", "--yes", "--profile", "demo"],
            catch_exceptions=False,
        )

        result = cli_runner.invoke(
            cli, ["--json", "deadlines", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert len(data["data"]) >= 2
        titles = [d["title"] for d in data["data"]]
        assert "File tax return" in titles
        assert "Renew car registration" in titles

    def test_deadlines_add_json(self, cli_runner):
        """circuit deadlines add --json creates a deadline."""
        result = cli_runner.invoke(
            cli,
            [
                "--json", "deadlines", "add",
                "--title", "Pay quarterly taxes",
                "--due-date", "2026-06-15",
                "--priority", "high",
                "--category", "tax",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"]["title"] == "Pay quarterly taxes"
        assert data["data"]["priority"] == "high"


class TestCLIJsonFlagPropagation:
    """Verify the --json flag works at different positions."""

    def test_json_at_root_level(self, cli_runner):
        """--json at root level propagates to subcommands."""
        result = cli_runner.invoke(
            cli, ["--json", "bills", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "status" in data

    def test_json_at_group_level(self, cli_runner):
        """--json at the subcommand group level also works."""
        result = cli_runner.invoke(
            cli, ["bills", "--json", "list"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "status" in data
