"""FastAPI application factory for CircuitAI web dashboard."""

from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from circuitai.web.auth import auth_router
from circuitai.web.routers.health import health_router

_WEB_DIR = Path(__file__).parent
_STATIC_DIR = _WEB_DIR / "static"


def create_app(encryption_key: str | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        encryption_key: Derived database encryption key (hex string).
                        None for test mode (unencrypted DB).
    """
    app = FastAPI(title="CircuitAI", docs_url=None, redoc_url=None)

    # Session middleware — random secret per run (local-only, no persistence needed)
    app.add_middleware(SessionMiddleware, secret_key=secrets.token_hex(32))

    # Store encryption key for dependency injection
    app.state.encryption_key = encryption_key

    # Static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Routers
    app.include_router(auth_router)
    app.include_router(health_router)

    @app.get("/")
    async def root():
        return RedirectResponse(url="/health", status_code=302)

    return app
