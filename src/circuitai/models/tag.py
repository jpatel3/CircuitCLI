"""Re-export tag models from category module for convenience."""

from circuitai.models.category import Tag, TagRepository

__all__ = ["Tag", "TagRepository"]
