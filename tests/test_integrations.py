"""Tests for the integrations registry and CLI command."""

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
from circuitai.services.integration_registry import (
    IntegrationInfo,
    IntegrationRegistry,
    IntegrationStatus,
)


@pytest.fixture
def tmp_db():
    """Create a temporary database with full schema."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        db_path = Path(tmp_dir) / "test_integrations.db"
        db = DatabaseConnection(db_path=db_path)
        db.connect()
        initialize_database(db)
        yield db
        db.close()


@pytest.fixture
def cli_runner(tmp_db):
    """CliRunner with patched database."""
    runner = CliRunner()

    def patched_get_db(self):
        self._db = tmp_db
        return tmp_db

    with patch.object(CircuitContext, "get_db", patched_get_db):
        yield runner


class TestIntegrationRegistry:
    """Tests for IntegrationRegistry service."""

    def test_list_all_includes_builtins(self, tmp_db):
        """list_all() returns at least the 4 built-in integrations."""
        registry = IntegrationRegistry(db=tmp_db)
        all_integrations = registry.list_all()
        names = [i.name for i in all_integrations]
        assert "calendar-sync" in names
        assert "statement-linker" in names
        assert "text-parser" in names
        assert "query-engine" in names

    def test_statement_linker_always_active(self, tmp_db):
        """statement-linker is always active with no external dependencies."""
        registry = IntegrationRegistry(db=tmp_db)
        info = registry.get("statement-linker")
        assert info is not None
        assert info.status == IntegrationStatus.active
        assert info.kind == "builtin"

    def test_to_dict_serialization(self):
        """IntegrationInfo.to_dict() returns a plain dict with string status."""
        info = IntegrationInfo(
            name="test",
            kind="builtin",
            description="A test integration",
            status=IntegrationStatus.active,
            status_detail="All good",
        )
        d = info.to_dict()
        assert d["name"] == "test"
        assert d["status"] == "active"
        assert d["kind"] == "builtin"
        assert d["description"] == "A test integration"
        assert isinstance(d, dict)

    def test_get_nonexistent_returns_none(self, tmp_db):
        """get() returns None for an unknown integration name."""
        registry = IntegrationRegistry(db=tmp_db)
        assert registry.get("nonexistent-integration") is None

    def test_list_all_includes_adapters(self, tmp_db):
        """list_all() includes registered adapter entry points."""
        registry = IntegrationRegistry(db=tmp_db)
        all_integrations = registry.list_all()
        names = [i.name for i in all_integrations]
        # manual and csv-import are registered in pyproject.toml
        assert "manual" in names
        assert "csv-import" in names

    def test_adapters_have_correct_kind(self, tmp_db):
        """Adapter integrations have kind='adapter'."""
        registry = IntegrationRegistry(db=tmp_db)
        info = registry.get("manual")
        assert info is not None
        assert info.kind == "adapter"


class TestIntegrationsCLI:
    """Tests for the `circuit integrations` CLI command."""

    def test_default_shows_list(self, cli_runner):
        """Running `circuit integrations` without subcommand shows all integrations."""
        result = cli_runner.invoke(cli, ["integrations"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "statement-linker" in result.output
        assert "calendar-sync" in result.output

    def test_json_returns_envelope(self, cli_runner):
        """`circuit --json integrations` returns valid JSON envelope."""
        result = cli_runner.invoke(
            cli, ["--json", "integrations"], catch_exceptions=False
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert isinstance(data["data"], list)
        names = [i["name"] for i in data["data"]]
        assert "statement-linker" in names

    def test_list_kind_builtin(self, cli_runner):
        """`circuit integrations list --kind builtin` filters to builtins only."""
        result = cli_runner.invoke(
            cli, ["--json", "integrations", "list", "--kind", "builtin"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        for item in data["data"]:
            assert item["kind"] == "builtin"

    def test_list_kind_adapter(self, cli_runner):
        """`circuit integrations list --kind adapter` filters to adapters only."""
        result = cli_runner.invoke(
            cli, ["--json", "integrations", "list", "--kind", "adapter"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        for item in data["data"]:
            assert item["kind"] == "adapter"

    def test_info_shows_detail(self, cli_runner):
        """`circuit integrations info statement-linker` shows detailed info."""
        result = cli_runner.invoke(
            cli, ["--json", "integrations", "info", "statement-linker"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "success"
        assert data["data"]["name"] == "statement-linker"
        assert data["data"]["status"] == "active"

    def test_info_nonexistent_shows_error(self, cli_runner):
        """`circuit integrations info nonexistent` shows an error."""
        result = cli_runner.invoke(
            cli, ["--json", "integrations", "info", "nonexistent"],
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["status"] == "error"
