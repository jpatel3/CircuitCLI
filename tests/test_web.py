"""Tests for web UI — FastAPI app, health dashboard, auth, HTMX partials."""

import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.services.lab_service import LabService
from circuitai.web.app import create_app
from circuitai.web.dependencies import get_db, require_auth


# ── Fixtures ──────────────────────────────────────────────────


class _ThreadSafeDbConnection(DatabaseConnection):
    """DatabaseConnection that allows cross-thread access for testing."""

    def connect(self) -> None:
        try:
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.row_factory = sqlite3.Row
        except Exception as e:
            from circuitai.core.exceptions import DatabaseError
            raise DatabaseError(f"Failed to connect: {e}") from e


@pytest.fixture
def db_path():
    """Temp directory for test DB — initialized once."""
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "test.db"
        conn = _ThreadSafeDbConnection(db_path=path)
        conn.connect()
        initialize_database(conn)
        conn.close()
        yield path


@pytest.fixture
def db(db_path):
    """DB connection for seeding data (test thread)."""
    conn = _ThreadSafeDbConnection(db_path=db_path)
    conn.connect()
    yield conn
    conn.close()


@pytest.fixture
def lab_svc(db):
    return LabService(db)


@pytest.fixture
def authenticated_client(db_path):
    """Test client with auth bypassed and DB dependency overridden."""
    application = create_app(encryption_key=None)

    def override_get_db():
        """Create a fresh thread-safe DB connection per request."""
        conn = _ThreadSafeDbConnection(db_path=db_path)
        conn.connect()
        try:
            yield conn
        finally:
            conn.close()

    def override_require_auth():
        return None

    application.dependency_overrides[get_db] = override_get_db
    application.dependency_overrides[require_auth] = override_require_auth

    with TestClient(application) as c:
        yield c


def _seed_result(lab_svc):
    """Import sample lab data and return result dict."""
    data = {
        "patient_name": "John Patel",
        "provider": "LabCorp",
        "ordering_physician": "Dr. Smith",
        "order_date": "2026-02-10",
        "result_date": "2026-02-15",
        "panels": [
            {
                "panel_name": "Complete Blood Count",
                "markers": [
                    {"marker_name": "WBC", "value": "6.2", "unit": "10^3/uL",
                     "reference_low": "4.0", "reference_high": "10.5", "flag": "normal"},
                    {"marker_name": "RBC", "value": "5.1", "unit": "10^6/uL",
                     "reference_low": "4.5", "reference_high": "5.5", "flag": "normal"},
                ],
            },
            {
                "panel_name": "Lipid Panel",
                "markers": [
                    {"marker_name": "Cholesterol", "value": "242", "unit": "mg/dL",
                     "reference_low": "125", "reference_high": "200", "flag": "high"},
                    {"marker_name": "HDL", "value": "45", "unit": "mg/dL",
                     "reference_low": "40", "reference_high": "", "flag": "normal"},
                    {"marker_name": "LDL", "value": "165", "unit": "mg/dL",
                     "reference_low": "", "reference_high": "130", "flag": "high"},
                ],
            },
        ],
    }
    return lab_svc.import_lab_data(data, source="pdf")


def _seed_multi_date_results(lab_svc):
    """Import 3 results on different dates with overlapping Cholesterol marker."""
    dates = [
        ("2024-01-15", "180", "normal"),
        ("2024-06-20", "205", "high"),
        ("2025-01-10", "165", "normal"),
    ]
    for result_date, chol_val, chol_flag in dates:
        data = {
            "patient_name": "John Patel",
            "provider": "LabCorp",
            "result_date": result_date,
            "panels": [{
                "panel_name": "Lipid Panel",
                "markers": [
                    {"marker_name": "Cholesterol, Total", "value": chol_val, "unit": "mg/dL",
                     "reference_low": "100", "reference_high": "199", "flag": chol_flag},
                ],
            }],
        }
        lab_svc.import_lab_data(data, source="pdf")


# ── App factory tests ─────────────────────────────────────────


class TestAppFactory:
    def test_creates_app(self):
        app = create_app()
        assert app.title == "CircuitAI"

    def test_root_redirects_to_health(self):
        app = create_app()
        with TestClient(app, follow_redirects=False) as c:
            resp = c.get("/")
            assert resp.status_code == 302
            assert resp.headers["location"] == "/health"

    def test_static_files_served(self):
        app = create_app()
        with TestClient(app) as c:
            resp = c.get("/static/css/custom.css")
            assert resp.status_code == 200
            assert "text/css" in resp.headers["content-type"]


# ── Auth tests ─────────────────────────────────────────────────


class TestAuth:
    def test_login_page_renders(self):
        app = create_app()
        with TestClient(app) as c:
            resp = c.get("/auth/login")
            assert resp.status_code == 200
            assert "Master Password" in resp.text
            assert "<form" in resp.text

    def test_logout_redirects(self):
        app = create_app()
        with TestClient(app, follow_redirects=False) as c:
            resp = c.get("/auth/logout")
            assert resp.status_code == 302
            assert "/auth/login" in resp.headers["location"]

    def test_login_invalid_password_returns_401(self):
        app = create_app()
        with TestClient(app) as c:
            resp = c.post("/auth/login", data={"password": "wrong"})
            assert resp.status_code == 401
            assert "Invalid master password" in resp.text


# ── Health dashboard tests ─────────────────────────────────────


class TestHealthDashboard:
    def test_dashboard_empty(self, authenticated_client):
        resp = authenticated_client.get("/health")
        assert resp.status_code == 200
        assert "Health Dashboard" in resp.text
        assert "No lab results yet" in resp.text

    def test_dashboard_with_results(self, authenticated_client, lab_svc):
        _seed_result(lab_svc)
        resp = authenticated_client.get("/health")
        assert resp.status_code == 200
        assert "Health Dashboard" in resp.text
        assert "LabCorp" in resp.text
        assert "2026-02-15" in resp.text

    def test_dashboard_shows_summary_cards(self, authenticated_client, lab_svc):
        _seed_result(lab_svc)
        resp = authenticated_client.get("/health")
        assert resp.status_code == 200
        assert "Total Results" in resp.text
        assert "Unreviewed" in resp.text
        assert "Flagged Markers" in resp.text

    def test_dashboard_shows_flagged_markers(self, authenticated_client, lab_svc):
        _seed_result(lab_svc)
        resp = authenticated_client.get("/health")
        assert resp.status_code == 200
        assert "Cholesterol" in resp.text


# ── Lab result detail tests ────────────────────────────────────


class TestResultDetail:
    def test_result_detail_page(self, authenticated_client, lab_svc):
        result = _seed_result(lab_svc)
        result_id = result["result_id"]
        resp = authenticated_client.get(f"/health/results/{result_id}")
        assert resp.status_code == 200
        assert "LabCorp" in resp.text
        assert "Complete Blood Count" in resp.text
        assert "Lipid Panel" in resp.text
        assert "WBC" in resp.text
        assert "Cholesterol" in resp.text

    def test_result_detail_404(self, authenticated_client):
        resp = authenticated_client.get("/health/results/nonexistent-id")
        assert resp.status_code == 404
        assert "Not Found" in resp.text or "not found" in resp.text.lower()

    def test_result_detail_shows_flags(self, authenticated_client, lab_svc):
        result = _seed_result(lab_svc)
        result_id = result["result_id"]
        resp = authenticated_client.get(f"/health/results/{result_id}")
        assert resp.status_code == 200
        assert "high" in resp.text.lower()

    def test_mark_reviewed(self, authenticated_client, lab_svc):
        result = _seed_result(lab_svc)
        result_id = result["result_id"]
        resp = authenticated_client.post(
            f"/health/results/{result_id}/review",
            follow_redirects=False,
        )
        assert resp.status_code == 302

    def test_mark_reviewed_htmx(self, authenticated_client, lab_svc):
        result = _seed_result(lab_svc)
        result_id = result["result_id"]
        resp = authenticated_client.post(
            f"/health/results/{result_id}/review",
            headers={"HX-Request": "true"},
        )
        assert resp.status_code == 200
        assert "reviewed" in resp.text


# ── Trends page tests ─────────────────────────────────────────


class TestTrends:
    def test_trends_page_with_data(self, authenticated_client, lab_svc):
        _seed_multi_date_results(lab_svc)
        resp = authenticated_client.get("/health/trends/Cholesterol%2C%20Total")
        assert resp.status_code == 200
        assert "Cholesterol, Total" in resp.text
        assert "trendChart" in resp.text

    def test_trends_page_empty(self, authenticated_client):
        resp = authenticated_client.get("/health/trends/Nonexistent")
        assert resp.status_code == 200
        assert "No trend data" in resp.text or "No data available" in resp.text

    def test_trends_shows_data_table(self, authenticated_client, lab_svc):
        _seed_multi_date_results(lab_svc)
        resp = authenticated_client.get("/health/trends/Cholesterol%2C%20Total")
        assert resp.status_code == 200
        assert "180" in resp.text
        assert "205" in resp.text
        assert "165" in resp.text


# ── HTMX partial tests ────────────────────────────────────────


class TestPartials:
    def test_marker_search_all(self, authenticated_client, lab_svc):
        _seed_result(lab_svc)
        resp = authenticated_client.get("/health/partials/marker-search")
        assert resp.status_code == 200
        assert "WBC" in resp.text
        assert "Cholesterol" in resp.text
        assert "<html" not in resp.text

    def test_marker_search_filtered(self, authenticated_client, lab_svc):
        _seed_result(lab_svc)
        resp = authenticated_client.get("/health/partials/marker-search?q=WBC")
        assert resp.status_code == 200
        assert "WBC" in resp.text
        assert "LDL" not in resp.text

    def test_marker_search_no_match(self, authenticated_client, lab_svc):
        _seed_result(lab_svc)
        resp = authenticated_client.get("/health/partials/marker-search?q=zzzzz")
        assert resp.status_code == 200
        assert "No markers found" in resp.text

    def test_health_summary_partial(self, authenticated_client, lab_svc):
        _seed_result(lab_svc)
        resp = authenticated_client.get("/health/partials/health-summary")
        assert resp.status_code == 200
        assert "Total Results" in resp.text
        assert "<html" not in resp.text

    def test_trend_chart_partial(self, authenticated_client, lab_svc):
        _seed_multi_date_results(lab_svc)
        resp = authenticated_client.get("/health/partials/trend-chart/Cholesterol%2C%20Total")
        assert resp.status_code == 200
        assert "trendChart" in resp.text
        assert "180" in resp.text
        assert "<html" not in resp.text

    def test_trend_chart_partial_empty(self, authenticated_client):
        resp = authenticated_client.get("/health/partials/trend-chart/Nonexistent")
        assert resp.status_code == 200
        assert "No data available" in resp.text


# ── Auth redirect tests ───────────────────────────────────────


class TestAuthRedirects:
    def test_health_requires_auth(self):
        app = create_app()
        with TestClient(app, follow_redirects=False) as c:
            resp = c.get("/health")
            assert resp.status_code == 302
            assert "/auth/login" in resp.headers["location"]

    def test_result_detail_requires_auth(self):
        app = create_app()
        with TestClient(app, follow_redirects=False) as c:
            resp = c.get("/health/results/some-id")
            assert resp.status_code == 302
            assert "/auth/login" in resp.headers["location"]

    def test_trends_requires_auth(self):
        app = create_app()
        with TestClient(app, follow_redirects=False) as c:
            resp = c.get("/health/trends/WBC")
            assert resp.status_code == 302
            assert "/auth/login" in resp.headers["location"]
