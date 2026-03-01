"""Authentication routes — master password login/logout."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from circuitai.web.templating import templates

auth_router = APIRouter(prefix="/auth", tags=["auth"])


@auth_router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the master password login form."""
    return templates.TemplateResponse(request, "login.html", {"error": None})


@auth_router.post("/login")
async def login_submit(request: Request):
    """Verify master password and create session."""
    form = await request.form()
    password = form.get("password", "")

    try:
        from circuitai.core.config import get_data_dir
        from circuitai.core.encryption import MasterKeyManager

        data_dir = get_data_dir()
        mgr = MasterKeyManager(data_dir)
        key = mgr.unlock(password)
        # Store derived key and mark session authenticated
        request.app.state.encryption_key = key
        request.session["authenticated"] = True
        return RedirectResponse(url="/health", status_code=302)
    except Exception:
        return templates.TemplateResponse(
            request, "login.html",
            {"error": "Invalid master password."},
            status_code=401,
        )


@auth_router.get("/logout")
async def logout(request: Request):
    """Clear session and redirect to login."""
    request.session.clear()
    return RedirectResponse(url="/auth/login", status_code=302)
