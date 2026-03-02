"""Health dashboard routes — lab results, marker trends, HTMX partials."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.responses import RedirectResponse

from circuitai.core.database import DatabaseConnection
from circuitai.services.lab_service import LabService
from circuitai.web.dependencies import get_db, require_auth
from circuitai.web.templating import templates

health_router = APIRouter(prefix="/health", tags=["health"])


def _get_lab_service(db: DatabaseConnection = Depends(get_db)) -> LabService:
    return LabService(db)


@health_router.get("", response_class=HTMLResponse)
async def health_dashboard(
    request: Request,
    auth_redirect=Depends(require_auth),
    lab_svc: LabService = Depends(_get_lab_service),
):
    """Main health dashboard page."""
    if auth_redirect:
        return auth_redirect

    summary = lab_svc.get_summary()
    results = lab_svc.list_results()
    enriched_results = []
    for r in results:
        panels = lab_svc.get_panels(r.id)
        flagged = lab_svc.get_flagged_markers(r.id)
        enriched_results.append({
            "result": r,
            "panel_count": len(panels),
            "flagged_count": len(flagged),
        })

    # Enrich flagged markers with result dates for the dashboard display
    flagged_rows = lab_svc.markers.db.fetchall(
        "SELECT m.*, r.result_date FROM lab_markers m "
        "JOIN lab_panels p ON m.lab_panel_id = p.id "
        "JOIN lab_results r ON p.lab_result_id = r.id "
        "WHERE m.flag != 'normal' AND r.status != 'reviewed' AND r.is_active = 1 "
        "ORDER BY r.result_date DESC, m.marker_name",
    )
    all_flagged = [dict(r) for r in flagged_rows]

    marker_names = lab_svc.list_marker_names()[:10]

    return templates.TemplateResponse(request, "health/dashboard.html", {
        "summary": summary,
        "results": enriched_results,
        "all_flagged": all_flagged,
        "marker_names": marker_names,
    })


@health_router.get("/results/{result_id}", response_class=HTMLResponse)
async def result_detail(
    request: Request,
    result_id: str,
    auth_redirect=Depends(require_auth),
    lab_svc: LabService = Depends(_get_lab_service),
):
    """Lab result detail page with panels and markers."""
    if auth_redirect:
        return auth_redirect

    try:
        detail = lab_svc.get_result_detail(result_id)
    except Exception:
        return templates.TemplateResponse(request, "health/not_found.html", {
            "message": "Lab result not found.",
        }, status_code=404)

    return templates.TemplateResponse(request, "health/result_detail.html", {
        "detail": detail,
    })


@health_router.post("/results/{result_id}/review", response_class=HTMLResponse)
async def mark_reviewed(
    request: Request,
    result_id: str,
    auth_redirect=Depends(require_auth),
    lab_svc: LabService = Depends(_get_lab_service),
):
    """Mark a lab result as reviewed (HTMX or full page)."""
    if auth_redirect:
        return auth_redirect

    try:
        result = lab_svc.mark_reviewed(result_id)
    except Exception:
        return HTMLResponse("<span class='error'>Failed to update.</span>", status_code=400)

    if request.headers.get("HX-Request"):
        return HTMLResponse(
            f'<span class="badge reviewed" id="status-badge">{result.status}</span>'
        )

    return RedirectResponse(url=f"/health/results/{result_id}", status_code=302)


@health_router.get("/trends/{marker_name}", response_class=HTMLResponse)
async def marker_trends(
    request: Request,
    marker_name: str,
    auth_redirect=Depends(require_auth),
    lab_svc: LabService = Depends(_get_lab_service),
):
    """Marker trend page with chart."""
    if auth_redirect:
        return auth_redirect

    trends = lab_svc.get_marker_trends(marker_name)
    marker_names = lab_svc.list_marker_names()

    return templates.TemplateResponse(request, "health/trends.html", {
        "marker_name": marker_name,
        "trends": trends,
        "marker_names": marker_names,
    })


# ── HTMX Partials ─────────────────────────────────────────────


@health_router.get("/partials/marker-search", response_class=HTMLResponse)
async def partial_marker_search(
    request: Request,
    q: str = "",
    auth_redirect=Depends(require_auth),
    lab_svc: LabService = Depends(_get_lab_service),
):
    """HTMX partial: filtered marker name list."""
    if auth_redirect:
        return auth_redirect

    all_names = lab_svc.list_marker_names()
    if q:
        filtered = [n for n in all_names if q.lower() in n.lower()]
    else:
        filtered = all_names

    return templates.TemplateResponse(request, "partials/marker_list.html", {
        "markers": filtered,
    })


@health_router.get("/partials/health-summary", response_class=HTMLResponse)
async def partial_health_summary(
    request: Request,
    auth_redirect=Depends(require_auth),
    lab_svc: LabService = Depends(_get_lab_service),
):
    """HTMX partial: refreshed summary cards."""
    if auth_redirect:
        return auth_redirect

    summary = lab_svc.get_summary()
    return templates.TemplateResponse(request, "partials/summary_cards.html", {
        "summary": summary,
    })


@health_router.get("/partials/trend-chart/{marker_name}", response_class=HTMLResponse)
async def partial_trend_chart(
    request: Request,
    marker_name: str,
    auth_redirect=Depends(require_auth),
    lab_svc: LabService = Depends(_get_lab_service),
):
    """HTMX partial: trend chart + data table for a marker."""
    if auth_redirect:
        return auth_redirect

    trends = lab_svc.get_marker_trends(marker_name)
    return templates.TemplateResponse(request, "partials/trend_chart.html", {
        "marker_name": marker_name,
        "trends": trends,
    })
