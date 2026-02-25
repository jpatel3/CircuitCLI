"""Adapter registry — discovers adapters via entry_points."""

from __future__ import annotations

# Python 3.10+ has importlib.metadata in stdlib
from importlib.metadata import entry_points
from typing import Any

from circuitai.adapters.protocol import CircuitAdapter
from circuitai.core.exceptions import AdapterError


class AdapterRegistry:
    """Discovers and loads CircuitAI adapters from entry_points."""

    ENTRY_POINT_GROUP = "circuitai.adapters"

    def __init__(self) -> None:
        self._adapters: dict[str, type] = {}
        self._loaded: dict[str, CircuitAdapter] = {}

    def _discover(self) -> dict[str, Any]:
        """Discover all registered adapter entry points."""
        eps = entry_points()
        # Python 3.12+ returns a SelectableGroups, 3.9-3.11 returns a dict
        if hasattr(eps, "select"):
            group = eps.select(group=self.ENTRY_POINT_GROUP)
        elif isinstance(eps, dict):
            group = eps.get(self.ENTRY_POINT_GROUP, [])
        else:
            group = [ep for ep in eps if ep.group == self.ENTRY_POINT_GROUP]

        return {ep.name: ep for ep in group}

    def list_adapters(self) -> list[dict[str, Any]]:
        """List all available adapters with metadata."""
        result = []
        for name, ep in self._discover().items():
            try:
                adapter_class = ep.load()
                adapter = adapter_class()
                meta = adapter.metadata()
                result.append({
                    "name": name,
                    "description": meta.get("description", ""),
                    "version": meta.get("version", "0.0.0"),
                    "author": meta.get("author", ""),
                })
            except Exception as e:
                result.append({
                    "name": name,
                    "description": f"(error loading: {e})",
                    "version": "?",
                })
        return result

    def get_adapter_info(self, name: str) -> dict[str, str]:
        """Get metadata for a specific adapter."""
        eps = self._discover()
        if name not in eps:
            raise AdapterError(f"Adapter not found: {name}")
        adapter_class = eps[name].load()
        adapter = adapter_class()
        return adapter.metadata()

    def load_adapter(self, name: str) -> CircuitAdapter:
        """Load and instantiate an adapter by name."""
        if name in self._loaded:
            return self._loaded[name]

        eps = self._discover()
        if name not in eps:
            raise AdapterError(f"Adapter not found: {name}")

        try:
            adapter_class = eps[name].load()
            adapter = adapter_class()
            if not isinstance(adapter, CircuitAdapter):
                raise AdapterError(f"Adapter '{name}' does not implement CircuitAdapter protocol")
            self._loaded[name] = adapter
            return adapter
        except AdapterError:
            raise
        except Exception as e:
            raise AdapterError(f"Failed to load adapter '{name}': {e}") from e
