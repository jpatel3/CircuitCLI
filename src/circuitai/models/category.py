"""Category and tag models."""

from __future__ import annotations

from typing import Any, ClassVar

from circuitai.models.base import BaseRepository, CircuitModel


# Standard bill categories
BILL_CATEGORIES = [
    "electricity", "water", "gas", "internet", "phone", "cable",
    "insurance_auto", "insurance_home", "insurance_umbrella", "insurance_life",
    "tax", "hoa", "subscription", "other",
]

# Standard investment account types
INVESTMENT_TYPES = [
    "brokerage", "401k", "529", "ira", "roth_ira", "hsa", "crypto", "other",
]

# Bill frequencies
FREQUENCIES = ["monthly", "quarterly", "semi-annual", "yearly", "one-time"]

# Priority levels
PRIORITIES = ["low", "medium", "high", "urgent"]


class Tag(CircuitModel):
    """A tag attached to any entity."""

    entity_type: str
    entity_id: str
    tag: str

    @classmethod
    def from_row(cls, row: Any) -> "Tag":
        d = {k: row[k] for k in row.keys()}
        return cls(**d)


class TagRepository(BaseRepository):
    table: ClassVar[str] = "tags"
    model_class: ClassVar[type[CircuitModel]] = Tag  # type: ignore[assignment]

    def get_for_entity(self, entity_type: str, entity_id: str) -> list[Tag]:
        rows = self.db.fetchall(
            "SELECT * FROM tags WHERE entity_type = ? AND entity_id = ?",
            (entity_type, entity_id),
        )
        return [Tag.from_row(r) for r in rows]

    def add_tag(self, entity_type: str, entity_id: str, tag: str) -> Tag:
        t = Tag(entity_type=entity_type, entity_id=entity_id, tag=tag)
        return self.insert(t)  # type: ignore[return-value]

    def remove_tag(self, entity_type: str, entity_id: str, tag: str) -> None:
        self.db.execute(
            "DELETE FROM tags WHERE entity_type = ? AND entity_id = ? AND tag = ?",
            (entity_type, entity_id, tag),
        )
        self.db.commit()

    def find_entities_by_tag(self, tag: str) -> list[Tag]:
        rows = self.db.fetchall("SELECT * FROM tags WHERE tag = ?", (tag,))
        return [Tag.from_row(r) for r in rows]

    def list_all(self, active_only: bool = True) -> list[Tag]:
        rows = self.db.fetchall("SELECT * FROM tags ORDER BY tag")
        return [Tag.from_row(r) for r in rows]
