"""Database connection — SQLite/SQLCipher wrapper with encrypted storage."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

from circuitai.core.config import get_data_dir
from circuitai.core.exceptions import DatabaseError

# Try SQLCipher, fall back to plain sqlite3
try:
    import sqlcipher3 as sqlcipher  # type: ignore[import-untyped]

    HAS_SQLCIPHER = True
except ImportError:
    HAS_SQLCIPHER = False

DB_FILENAME = "circuitai.db"


class DatabaseConnection:
    """Manages a connection to the CircuitAI SQLite/SQLCipher database."""

    def __init__(
        self,
        db_path: Path | None = None,
        encryption_key: str | None = None,
    ) -> None:
        self.db_path = db_path or (get_data_dir() / DB_FILENAME)
        self.encryption_key = encryption_key
        self._conn: sqlite3.Connection | None = None

    def connect(self) -> None:
        """Open the database connection."""
        try:
            if self.encryption_key and HAS_SQLCIPHER:
                self._conn = sqlcipher.connect(str(self.db_path))
                self._conn.execute(f"PRAGMA key = \"x'{self.encryption_key}'\"")
                self._conn.execute("PRAGMA cipher_memory_security = ON")
            else:
                self._conn = sqlite3.connect(str(self.db_path))

            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.row_factory = sqlite3.Row
        except Exception as e:
            raise DatabaseError(f"Failed to connect to database: {e}") from e

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> sqlite3.Connection:
        """Return the active connection, raising if not connected."""
        if self._conn is None:
            raise DatabaseError("Database not connected. Call connect() first.")
        return self._conn

    def execute(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Cursor:
        """Execute a SQL statement."""
        try:
            return self.conn.execute(sql, params)
        except Exception as e:
            raise DatabaseError(f"SQL error: {e}\nQuery: {sql}") from e

    def executemany(self, sql: str, params_seq: list[tuple[Any, ...]]) -> sqlite3.Cursor:
        """Execute a SQL statement with multiple parameter sets."""
        try:
            return self.conn.executemany(sql, params_seq)
        except Exception as e:
            raise DatabaseError(f"SQL error: {e}\nQuery: {sql}") from e

    def fetchone(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> sqlite3.Row | None:
        """Execute and fetch one row."""
        return self.execute(sql, params).fetchone()

    def fetchall(self, sql: str, params: tuple[Any, ...] | dict[str, Any] = ()) -> list[sqlite3.Row]:
        """Execute and fetch all rows."""
        return self.execute(sql, params).fetchall()

    def commit(self) -> None:
        """Commit the current transaction."""
        self.conn.commit()

    def rollback(self) -> None:
        """Rollback the current transaction."""
        self.conn.rollback()

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Context manager for a database transaction."""
        try:
            yield
            self.commit()
        except Exception:
            self.rollback()
            raise

    def __enter__(self) -> "DatabaseConnection":
        self.connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
