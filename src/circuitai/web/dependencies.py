"""FastAPI dependencies — database connection and auth checks."""

from __future__ import annotations

import sqlite3

from fastapi import Request
from starlette.responses import RedirectResponse

from circuitai.core.database import DatabaseConnection, HAS_SQLCIPHER
from circuitai.core.exceptions import DatabaseError


def get_db(request: Request):
    """Create a per-request database connection (thread-safe for uvicorn)."""
    key = request.app.state.encryption_key
    db = DatabaseConnection(encryption_key=key)
    try:
        # Use check_same_thread=False — uvicorn dispatches sync handlers
        # to a thread pool, so the connection may be used in a different
        # thread than the one that created it. Each request gets its own
        # connection so there's no concurrent access.
        if key and HAS_SQLCIPHER:
            import sqlcipher3 as sqlcipher  # type: ignore[import-untyped]
            db._conn = sqlcipher.connect(str(db.db_path), check_same_thread=False)
            db._conn.execute(f"PRAGMA key = \"x'{key}'\"")
            db._conn.execute("PRAGMA cipher_memory_security = ON")
        else:
            db._conn = sqlite3.connect(str(db.db_path), check_same_thread=False)
        db._conn.execute("PRAGMA journal_mode = WAL")
        db._conn.execute("PRAGMA foreign_keys = ON")
        db._conn.row_factory = sqlite3.Row
    except Exception as e:
        raise DatabaseError(f"Failed to connect to database: {e}") from e
    try:
        yield db
    finally:
        db.close()


def require_auth(request: Request):
    """Check session for authentication; redirect to login if not authenticated.

    Returns None if authenticated, or a RedirectResponse to login.
    Used as a FastAPI dependency.
    """
    if not request.session.get("authenticated"):
        return RedirectResponse(url="/auth/login", status_code=302)
    return None
