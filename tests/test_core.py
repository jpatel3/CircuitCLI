"""Tests for core infrastructure."""

import tempfile
from pathlib import Path

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.encryption import MasterKeyManager
from circuitai.core.migrations import get_schema_version, initialize_database


@pytest.fixture
def tmp_dir():
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def db(tmp_dir):
    """Create a fresh unencrypted test database."""
    conn = DatabaseConnection(db_path=tmp_dir / "test.db")
    conn.connect()
    initialize_database(conn)
    yield conn
    conn.close()


class TestEncryption:
    def test_initialize_and_unlock(self, tmp_dir):
        mgr = MasterKeyManager(data_dir=tmp_dir)
        assert not mgr.is_initialized

        key = mgr.initialize("test-password")
        assert mgr.is_initialized
        assert len(key) == 64  # 32 bytes hex

        # Unlock with correct password
        key2 = mgr.unlock("test-password")
        assert key == key2

    def test_wrong_password(self, tmp_dir):
        mgr = MasterKeyManager(data_dir=tmp_dir)
        mgr.initialize("correct")

        from circuitai.core.exceptions import EncryptionError
        with pytest.raises(EncryptionError, match="Incorrect"):
            mgr.unlock("wrong")

    def test_double_initialize(self, tmp_dir):
        mgr = MasterKeyManager(data_dir=tmp_dir)
        mgr.initialize("pw")

        from circuitai.core.exceptions import EncryptionError
        with pytest.raises(EncryptionError, match="already initialized"):
            mgr.initialize("pw2")

    def test_reset(self, tmp_dir):
        mgr = MasterKeyManager(data_dir=tmp_dir)
        mgr.initialize("pw")
        assert mgr.is_initialized
        mgr.reset()
        assert not mgr.is_initialized


class TestDatabase:
    def test_connect_and_query(self, tmp_dir):
        conn = DatabaseConnection(db_path=tmp_dir / "test.db")
        conn.connect()
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO test VALUES (1, 'hello')")
        conn.commit()
        row = conn.fetchone("SELECT * FROM test WHERE id = 1")
        assert row["name"] == "hello"
        conn.close()

    def test_transaction_rollback(self, tmp_dir):
        conn = DatabaseConnection(db_path=tmp_dir / "test.db")
        conn.connect()
        conn.execute("CREATE TABLE test (id INTEGER PRIMARY KEY)")
        conn.commit()

        try:
            with conn.transaction():
                conn.execute("INSERT INTO test VALUES (1)")
                raise ValueError("oops")
        except ValueError:
            pass

        row = conn.fetchone("SELECT COUNT(*) as cnt FROM test")
        assert row["cnt"] == 0
        conn.close()


class TestMigrations:
    def test_initialize_creates_tables(self, db):
        version = get_schema_version(db)
        assert version == 1

        # Check that core tables exist
        tables = db.fetchall(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        table_names = [t["name"] for t in tables]
        assert "bills" in table_names
        assert "accounts" in table_names
        assert "cards" in table_names
        assert "mortgages" in table_names
        assert "investments" in table_names
        assert "deadlines" in table_names
        assert "children" in table_names
        assert "activities" in table_names
        assert "tags" in table_names
        assert "schema_version" in table_names
