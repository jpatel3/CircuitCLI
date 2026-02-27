"""Site adapter registry — discover and register browser-automated site adapters."""

from __future__ import annotations

from typing import Any

from circuitai.services.sites.base import BaseSite

SITE_REGISTRY: dict[str, type[BaseSite]] = {}


def register_site(key: str):
    """Decorator to register a site adapter class.

    Usage:
        @register_site("jcpl")
        class JCPLSite(BaseSite): ...
    """
    def wrapper(cls: type[BaseSite]) -> type[BaseSite]:
        SITE_REGISTRY[key] = cls
        return cls
    return wrapper


def get_site(key: str) -> type[BaseSite]:
    """Get a registered site adapter class by key."""
    if key not in SITE_REGISTRY:
        available = ", ".join(sorted(SITE_REGISTRY.keys())) or "(none)"
        raise KeyError(f"Unknown site '{key}'. Available: {available}")
    return SITE_REGISTRY[key]


def list_sites() -> list[dict[str, Any]]:
    """List all registered site adapters with metadata."""
    return [
        {"key": k, "name": v.DISPLAY_NAME, "domain": v.DOMAIN, "category": v.BILL_CATEGORY}
        for k, v in sorted(SITE_REGISTRY.items())
    ]


# Import site modules so their @register_site decorators execute
from circuitai.services.sites import jcpl as _jcpl  # noqa: F401, E402
from circuitai.services.sites import labcorp as _labcorp  # noqa: F401, E402
