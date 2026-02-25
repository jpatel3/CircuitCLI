"""Base model and repository classes for CircuitAI."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, ClassVar

from pydantic import BaseModel, Field

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import NotFoundError


def new_id() -> str:
    """Generate a new UUID string."""
    return str(uuid.uuid4())


def now_iso() -> str:
    """Return current UTC datetime as ISO string."""
    return datetime.utcnow().isoformat()


class CircuitModel(BaseModel):
    """Base for all CircuitAI Pydantic models."""

    id: str = Field(default_factory=new_id)
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)

    def to_row(self) -> dict[str, Any]:
        """Convert model to a flat dict suitable for DB insertion."""
        return self.model_dump()

    @classmethod
    def from_row(cls, row: Any) -> "CircuitModel":
        """Create model from a sqlite3.Row or dict."""
        if hasattr(row, "keys"):
            return cls(**{k: row[k] for k in row.keys()})
        return cls(**row)


class BaseRepository:
    """Generic CRUD repository backed by SQLite."""

    table: ClassVar[str] = ""
    model_class: ClassVar[type[CircuitModel]] = CircuitModel

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db

    def insert(self, model: CircuitModel) -> CircuitModel:
        """Insert a new record."""
        data = model.to_row()
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        self.db.execute(f"INSERT INTO {self.table} ({cols}) VALUES ({placeholders})", data)
        self.db.commit()
        return model

    def get(self, entity_id: str) -> CircuitModel:
        """Fetch a single record by ID."""
        row = self.db.fetchone(f"SELECT * FROM {self.table} WHERE id = ?", (entity_id,))
        if row is None:
            raise NotFoundError(f"{self.model_class.__name__} not found: {entity_id}")
        return self.model_class.from_row(row)

    def list_all(self, active_only: bool = True) -> list[CircuitModel]:
        """List all records, optionally filtering to active ones."""
        sql = f"SELECT * FROM {self.table}"
        if active_only and "is_active" in self._column_names():
            sql += " WHERE is_active = 1"
        sql += " ORDER BY created_at DESC"
        rows = self.db.fetchall(sql)
        return [self.model_class.from_row(r) for r in rows]

    def update(self, entity_id: str, **updates: Any) -> CircuitModel:
        """Update specific fields on a record."""
        updates["updated_at"] = now_iso()
        set_clause = ", ".join(f"{k} = :{k}" for k in updates.keys())
        updates["_id"] = entity_id
        self.db.execute(
            f"UPDATE {self.table} SET {set_clause} WHERE id = :_id",
            updates,
        )
        self.db.commit()
        return self.get(entity_id)

    def delete(self, entity_id: str) -> None:
        """Delete a record by ID (hard delete)."""
        self.db.execute(f"DELETE FROM {self.table} WHERE id = ?", (entity_id,))
        self.db.commit()

    def soft_delete(self, entity_id: str) -> None:
        """Soft-delete by setting is_active = 0."""
        self.update(entity_id, is_active=0)

    def count(self, where: str = "", params: tuple = ()) -> int:
        """Count records with optional WHERE clause."""
        sql = f"SELECT COUNT(*) as cnt FROM {self.table}"
        if where:
            sql += f" WHERE {where}"
        row = self.db.fetchone(sql, params)
        return row["cnt"] if row else 0

    def _column_names(self) -> list[str]:
        """Get column names for this table."""
        cursor = self.db.execute(f"PRAGMA table_info({self.table})")
        return [row["name"] for row in cursor.fetchall()]
