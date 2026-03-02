"""Subscriptions dashboard routes — management, detection, HTMX partials."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from circuitai.core.database import DatabaseConnection
from circuitai.services.subscription_service import SubscriptionService
from circuitai.web.dependencies import get_db, require_auth
from circuitai.web.templating import templates

subs_router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


def _get_sub_service(db: DatabaseConnection = Depends(get_db)) -> SubscriptionService:
    return SubscriptionService(db)


# ── Full pages ────────────────────────────────────────────────


@subs_router.get("", response_class=HTMLResponse)
async def subscriptions_dashboard(
    request: Request,
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """Main subscriptions dashboard page."""
    if auth_redirect:
        return auth_redirect

    subs = sub_svc.list_subscriptions(active_only=False)
    summary = sub_svc.get_summary()

    return templates.TemplateResponse(request, "subscriptions/dashboard.html", {
        "subscriptions": subs,
        "summary": summary,
    })


@subs_router.get("/add", response_class=HTMLResponse)
async def add_form(
    request: Request,
    auth_redirect=Depends(require_auth),
):
    """Render add subscription form."""
    if auth_redirect:
        return auth_redirect

    return templates.TemplateResponse(request, "subscriptions/add.html", {})


@subs_router.post("/add", response_class=HTMLResponse)
async def add_submit(
    request: Request,
    name: str = Form(...),
    amount: float = Form(0.0),
    frequency: str = Form("monthly"),
    category: str = Form("other"),
    notes: str = Form(""),
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """Submit add subscription form."""
    if auth_redirect:
        return auth_redirect

    amount_cents = int(round(amount * 100))
    sub_svc.add_subscription(
        name=name,
        amount_cents=amount_cents,
        frequency=frequency,
        category=category,
        notes=notes,
    )
    return RedirectResponse(url="/subscriptions", status_code=302)


@subs_router.get("/detect", response_class=HTMLResponse)
async def detect_page(
    request: Request,
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """Show auto-detected subscriptions."""
    if auth_redirect:
        return auth_redirect

    detected = sub_svc.detect_subscriptions()

    return templates.TemplateResponse(request, "subscriptions/detect.html", {
        "detected": detected,
    })


@subs_router.post("/detect/confirm", response_class=HTMLResponse)
async def detect_confirm(
    request: Request,
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """Confirm all detected subscriptions."""
    if auth_redirect:
        return auth_redirect

    detected = sub_svc.detect_subscriptions()
    sub_svc.confirm_detected(detected)
    return RedirectResponse(url="/subscriptions", status_code=302)


@subs_router.get("/{sub_id}", response_class=HTMLResponse)
async def subscription_detail(
    request: Request,
    sub_id: str,
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """Single subscription detail page."""
    if auth_redirect:
        return auth_redirect

    try:
        sub = sub_svc.get_subscription(sub_id)
    except Exception:
        return templates.TemplateResponse(request, "subscriptions/not_found.html", {
            "message": "Subscription not found.",
        }, status_code=404)

    return templates.TemplateResponse(request, "subscriptions/detail.html", {
        "sub": sub,
    })


@subs_router.post("/{sub_id}/cancel", response_class=HTMLResponse)
async def cancel_subscription(
    request: Request,
    sub_id: str,
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """Cancel a subscription (HTMX badge swap or redirect)."""
    if auth_redirect:
        return auth_redirect

    try:
        sub = sub_svc.cancel_subscription(sub_id)
    except Exception:
        return HTMLResponse("<span class='error'>Failed to cancel.</span>", status_code=400)

    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<span class="badge cancelled" id="status-badge">{sub.status}</span>'
        )

    return RedirectResponse(url=f"/subscriptions/{sub_id}", status_code=302)


# ── HTMX Partials ─────────────────────────────────────────────


@subs_router.get("/partials/sub-search", response_class=HTMLResponse)
async def partial_sub_search(
    request: Request,
    q: str = "",
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """HTMX partial: filtered subscription list."""
    if auth_redirect:
        return auth_redirect

    subs = sub_svc.list_subscriptions(active_only=False)
    if q:
        subs = [s for s in subs if q.lower() in s.name.lower()]

    return templates.TemplateResponse(request, "partials/sub_list.html", {
        "subscriptions": subs,
    })


@subs_router.get("/partials/sub-summary", response_class=HTMLResponse)
async def partial_sub_summary(
    request: Request,
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """HTMX partial: refreshed summary cards."""
    if auth_redirect:
        return auth_redirect

    summary = sub_svc.get_summary()
    return templates.TemplateResponse(request, "partials/sub_summary_cards.html", {
        "summary": summary,
    })


@subs_router.get("/partials/category-chart", response_class=HTMLResponse)
async def partial_category_chart(
    request: Request,
    auth_redirect=Depends(require_auth),
    sub_svc: SubscriptionService = Depends(_get_sub_service),
):
    """HTMX partial: category doughnut chart."""
    if auth_redirect:
        return auth_redirect

    summary = sub_svc.get_summary()
    return templates.TemplateResponse(request, "partials/category_chart.html", {
        "summary": summary,
    })
