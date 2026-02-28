"""Tests for health tracking — lab results, panels, markers, PDF extraction, CLI."""

import tempfile
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.models.lab import (
    LabMarker,
    LabMarkerRepository,
    LabPanel,
    LabPanelRepository,
    LabResult,
    LabResultRepository,
)
from circuitai.services.lab_service import (
    LabService,
    compute_lab_fingerprint,
)


# ── Fixtures ──────────────────────────────────────────────────


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


@pytest.fixture
def lab_svc(db):
    return LabService(db)


@pytest.fixture
def result_repo(db):
    return LabResultRepository(db)


@pytest.fixture
def panel_repo(db):
    return LabPanelRepository(db)


@pytest.fixture
def marker_repo(db):
    return LabMarkerRepository(db)


def _sample_lab_data():
    """Return a dict mimicking parsed PDF data with 2 panels, 5 markers."""
    return {
        "patient_name": "John Patel",
        "provider": "LabCorp",
        "ordering_physician": "Dr. Smith",
        "order_date": "2026-02-10",
        "result_date": "2026-02-15",
        "panels": [
            {
                "panel_name": "Complete Blood Count",
                "markers": [
                    {"marker_name": "WBC", "value": "6.2", "unit": "10^3/uL", "reference_low": "4.0", "reference_high": "10.5", "flag": "normal"},
                    {"marker_name": "RBC", "value": "5.1", "unit": "10^6/uL", "reference_low": "4.5", "reference_high": "5.5", "flag": "normal"},
                ],
            },
            {
                "panel_name": "Lipid Panel",
                "markers": [
                    {"marker_name": "Cholesterol", "value": "242", "unit": "mg/dL", "reference_low": "125", "reference_high": "200", "flag": "high"},
                    {"marker_name": "HDL", "value": "45", "unit": "mg/dL", "reference_low": "40", "reference_high": "", "flag": "normal"},
                    {"marker_name": "LDL", "value": "165", "unit": "mg/dL", "reference_low": "", "reference_high": "130", "flag": "high"},
                ],
            },
        ],
    }


def _seed_full_result(lab_svc):
    """Import sample data and return the result dict."""
    return lab_svc.import_lab_data(_sample_lab_data(), source="pdf")


# ── Model tests ───────────────────────────────────────────────


class TestLabResultModel:
    def test_create_defaults(self):
        r = LabResult(patient_name="Test Patient", provider="LabCorp")
        assert r.patient_name == "Test Patient"
        assert r.provider == "LabCorp"
        assert r.status == "completed"
        assert r.source == "pdf"
        assert r.is_active is True
        assert r.id  # UUID generated

    def test_to_row_bool_conversion(self):
        r = LabResult(patient_name="Test", is_active=True)
        row = r.to_row()
        assert row["is_active"] == 1

        r2 = LabResult(patient_name="Test", is_active=False)
        row2 = r2.to_row()
        assert row2["is_active"] == 0

    def test_from_row_bool_conversion(self):
        r = LabResult(patient_name="Test")
        row = r.to_row()
        reconstructed = LabResult.from_row(type("Row", (), {"keys": lambda s: row.keys(), "__getitem__": lambda s, k: row[k]})())
        assert reconstructed.is_active is True


class TestLabPanelModel:
    def test_create(self):
        p = LabPanel(lab_result_id="abc", panel_name="CBC", status="abnormal")
        assert p.panel_name == "CBC"
        assert p.status == "abnormal"

    def test_to_row_excludes_updated_at(self):
        p = LabPanel(lab_result_id="abc", panel_name="CBC")
        row = p.to_row()
        assert "updated_at" not in row


class TestLabMarkerModel:
    def test_create(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="WBC", value="6.2", unit="10^3/uL")
        assert m.marker_name == "WBC"
        assert m.flag == "normal"

    def test_is_flagged_normal(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="WBC", flag="normal")
        assert m.is_flagged is False

    def test_is_flagged_high(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="Cholesterol", flag="high")
        assert m.is_flagged is True

    def test_is_flagged_low(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="RBC", flag="low")
        assert m.is_flagged is True

    def test_is_flagged_critical(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="Glucose", flag="critical")
        assert m.is_flagged is True

    def test_reference_range_both(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="WBC", reference_low="4.0", reference_high="10.5")
        assert m.reference_range == "4.0 - 10.5"

    def test_reference_range_low_only(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="HDL", reference_low="40")
        assert m.reference_range == ">= 40"

    def test_reference_range_high_only(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="LDL", reference_high="130")
        assert m.reference_range == "< 130"

    def test_reference_range_none(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="Notes")
        assert m.reference_range == ""

    def test_to_row_excludes_updated_at(self):
        m = LabMarker(lab_panel_id="xyz", marker_name="WBC")
        row = m.to_row()
        assert "updated_at" not in row


# ── Repository tests ──────────────────────────────────────────


class TestLabResultRepository:
    def test_insert_and_get(self, result_repo):
        r = LabResult(patient_name="Test", provider="LabCorp")
        result_repo.insert(r)
        fetched = result_repo.get(r.id)
        assert fetched.patient_name == "Test"
        assert fetched.provider == "LabCorp"

    def test_list_all(self, result_repo):
        r1 = LabResult(patient_name="A", provider="LabCorp")
        r2 = LabResult(patient_name="B", provider="Quest")
        result_repo.insert(r1)
        result_repo.insert(r2)
        results = result_repo.list_all()
        assert len(results) == 2

    def test_find_by_fingerprint_found(self, result_repo):
        r = LabResult(patient_name="Test", report_fingerprint="abc123")
        result_repo.insert(r)
        found = result_repo.find_by_fingerprint("abc123")
        assert found is not None
        assert found.id == r.id

    def test_find_by_fingerprint_not_found(self, result_repo):
        assert result_repo.find_by_fingerprint("nonexistent") is None

    def test_find_by_status(self, result_repo):
        r1 = LabResult(patient_name="A", status="completed")
        r2 = LabResult(patient_name="B", status="reviewed")
        result_repo.insert(r1)
        result_repo.insert(r2)
        completed = result_repo.find_by_status("completed")
        assert len(completed) == 1
        assert completed[0].patient_name == "A"

    def test_get_recent(self, result_repo):
        for i in range(15):
            result_repo.insert(LabResult(patient_name=f"Patient {i}", result_date=f"2026-01-{i+1:02d}"))
        recent = result_repo.get_recent(limit=5)
        assert len(recent) == 5


class TestLabPanelRepository:
    def test_get_for_result(self, db, result_repo, panel_repo):
        r = LabResult(patient_name="Test")
        result_repo.insert(r)

        p1 = LabPanel(lab_result_id=r.id, panel_name="CBC")
        p2 = LabPanel(lab_result_id=r.id, panel_name="Lipid Panel")
        panel_repo.insert(p1)
        panel_repo.insert(p2)

        panels = panel_repo.get_for_result(r.id)
        assert len(panels) == 2
        names = {p.panel_name for p in panels}
        assert "CBC" in names
        assert "Lipid Panel" in names


class TestLabMarkerRepository:
    def test_get_for_panel(self, db, result_repo, panel_repo, marker_repo):
        r = LabResult(patient_name="Test")
        result_repo.insert(r)
        p = LabPanel(lab_result_id=r.id, panel_name="CBC")
        panel_repo.insert(p)

        m1 = LabMarker(lab_panel_id=p.id, marker_name="WBC", value="6.2")
        m2 = LabMarker(lab_panel_id=p.id, marker_name="RBC", value="5.1")
        marker_repo.insert(m1)
        marker_repo.insert(m2)

        markers = marker_repo.get_for_panel(p.id)
        assert len(markers) == 2

    def test_get_flagged_for_result(self, lab_svc):
        result = _seed_full_result(lab_svc)
        flagged = lab_svc.markers.get_flagged_for_result(result["result_id"])
        # Cholesterol and LDL are flagged high
        assert len(flagged) == 2
        names = {m.marker_name for m in flagged}
        assert "Cholesterol" in names
        assert "LDL" in names

    def test_get_all_flagged_unreviewed_only(self, lab_svc):
        result = _seed_full_result(lab_svc)
        # Before review: flagged markers visible
        flagged = lab_svc.markers.get_all_flagged()
        assert len(flagged) == 2

        # After review: no longer in all_flagged
        lab_svc.mark_reviewed(result["result_id"])
        flagged = lab_svc.markers.get_all_flagged()
        assert len(flagged) == 0


# ── Fingerprint tests ─────────────────────────────────────────


class TestLabFingerprint:
    def test_deterministic(self):
        fp1 = compute_lab_fingerprint("2026-02-15", "LabCorp", "John Patel")
        fp2 = compute_lab_fingerprint("2026-02-15", "LabCorp", "John Patel")
        assert fp1 == fp2

    def test_different_dates(self):
        fp1 = compute_lab_fingerprint("2026-02-15", "LabCorp", "John Patel")
        fp2 = compute_lab_fingerprint("2026-03-15", "LabCorp", "John Patel")
        assert fp1 != fp2

    def test_normalization_case_insensitive(self):
        fp1 = compute_lab_fingerprint("2026-02-15", "LabCorp", "John Patel")
        fp2 = compute_lab_fingerprint("2026-02-15", "LABCORP", "JOHN PATEL")
        assert fp1 == fp2

    def test_normalization_ignores_punctuation(self):
        fp1 = compute_lab_fingerprint("2026-02-15", "Lab Corp", "John P. Patel")
        fp2 = compute_lab_fingerprint("2026-02-15", "LabCorp", "John P Patel")
        assert fp1 == fp2


# ── PDF text extraction tests ─────────────────────────────────


class TestPdfTextExtraction:
    def test_extract_patient_name(self, lab_svc):
        text = "Patient Name: John Doe\nDate Reported: 02/15/2026"
        data = lab_svc.extract_from_pdf_text(text)
        assert data["patient_name"] == "John Doe"

    def test_extract_provider_labcorp(self, lab_svc):
        text = "Laboratory Corporation of America (LabCorp)\nResults"
        data = lab_svc.extract_from_pdf_text(text)
        assert data["provider"] == "LabCorp"

    def test_extract_provider_quest(self, lab_svc):
        text = "Quest Diagnostics\nResults"
        data = lab_svc.extract_from_pdf_text(text)
        assert data["provider"] == "Quest Diagnostics"

    def test_extract_dates(self, lab_svc):
        text = "Date Collected: 02/10/2026\nDate Reported: 02/15/2026"
        data = lab_svc.extract_from_pdf_text(text)
        assert data["order_date"] == "2026-02-10"
        assert data["result_date"] == "2026-02-15"

    def test_extract_physician(self, lab_svc):
        text = "Ordering Physician: Dr. Smith"
        data = lab_svc.extract_from_pdf_text(text)
        assert data["ordering_physician"] == "Dr. Smith"

    def test_extract_markers_tabular(self, lab_svc):
        text = (
            "COMPLETE BLOOD COUNT\n"
            "WBC          6.2    10^3/uL    4.0 - 10.5\n"
            "RBC          5.1    10^6/uL    4.5 - 5.5\n"
            "Hemoglobin   15.2   g/dL       13.5 - 17.5\n"
        )
        data = lab_svc.extract_from_pdf_text(text)
        assert len(data["panels"]) == 1
        panel = data["panels"][0]
        assert panel["panel_name"] == "Complete Blood Count"
        assert len(panel["markers"]) == 3
        wbc = panel["markers"][0]
        assert wbc["marker_name"] == "WBC"
        assert wbc["value"] == "6.2"
        assert wbc["unit"] == "10^3/uL"
        assert wbc["reference_low"] == "4.0"
        assert wbc["reference_high"] == "10.5"

    def test_extract_markers_with_flag(self, lab_svc):
        text = (
            "LIPID PANEL\n"
            "Cholesterol  242    mg/dL    125 - 200    H\n"
        )
        data = lab_svc.extract_from_pdf_text(text)
        assert len(data["panels"]) == 1
        marker = data["panels"][0]["markers"][0]
        assert marker["flag"] == "high"

    def test_empty_text(self, lab_svc):
        data = lab_svc.extract_from_pdf_text("")
        assert data["patient_name"] == ""
        assert data["panels"] == []

    def test_missing_fields_graceful(self, lab_svc):
        text = "Some random text without any lab data"
        data = lab_svc.extract_from_pdf_text(text)
        assert data["patient_name"] == ""
        assert data["provider"] == ""
        assert data["panels"] == []


# ── Import tests ──────────────────────────────────────────────


class TestLabImport:
    def test_import_sample_data(self, lab_svc):
        result = _seed_full_result(lab_svc)
        assert result["panels_imported"] == 2
        assert result["markers_imported"] == 5
        assert result["flagged_count"] == 2
        assert result["result_id"]

    def test_duplicate_fingerprint_skip(self, lab_svc):
        data = _sample_lab_data()
        data["report_fingerprint"] = "test_fingerprint_123"
        lab_svc.import_lab_data(data, source="pdf")

        # Check that the fingerprint is detected as duplicate
        existing = lab_svc._check_duplicate("test_fingerprint_123")
        assert existing is not None

    def test_panel_status_all_normal(self, lab_svc):
        data = {
            "patient_name": "Test",
            "provider": "LabCorp",
            "panels": [{
                "panel_name": "Metabolic",
                "markers": [
                    {"marker_name": "Glucose", "value": "95", "unit": "mg/dL", "flag": "normal"},
                    {"marker_name": "BUN", "value": "15", "unit": "mg/dL", "flag": "normal"},
                ],
            }],
        }
        result = lab_svc.import_lab_data(data)
        panels = lab_svc.get_panels(result["result_id"])
        assert panels[0].status == "normal"

    def test_panel_status_abnormal(self, lab_svc):
        data = {
            "patient_name": "Test",
            "provider": "LabCorp",
            "panels": [{
                "panel_name": "Lipid",
                "markers": [
                    {"marker_name": "Cholesterol", "value": "242", "flag": "high"},
                    {"marker_name": "HDL", "value": "45", "flag": "normal"},
                ],
            }],
        }
        result = lab_svc.import_lab_data(data)
        panels = lab_svc.get_panels(result["result_id"])
        assert panels[0].status == "abnormal"

    def test_panel_status_critical(self, lab_svc):
        data = {
            "patient_name": "Test",
            "provider": "LabCorp",
            "panels": [{
                "panel_name": "Glucose",
                "markers": [
                    {"marker_name": "Glucose", "value": "400", "flag": "critical"},
                ],
            }],
        }
        result = lab_svc.import_lab_data(data)
        panels = lab_svc.get_panels(result["result_id"])
        assert panels[0].status == "critical"

    def test_missing_panel_name_defaults(self, lab_svc):
        data = {
            "patient_name": "Test",
            "provider": "LabCorp",
            "panels": [{
                "markers": [
                    {"marker_name": "Glucose", "value": "95", "flag": "normal"},
                ],
            }],
        }
        result = lab_svc.import_lab_data(data)
        panels = lab_svc.get_panels(result["result_id"])
        assert panels[0].panel_name == "General"

    def test_import_empty_panels(self, lab_svc):
        data = {"patient_name": "Test", "provider": "LabCorp", "panels": []}
        result = lab_svc.import_lab_data(data)
        assert result["panels_imported"] == 0
        assert result["markers_imported"] == 0


# ── Vision API tests ──────────────────────────────────────────


class TestVisionExtraction:
    def test_vision_api_not_available(self, lab_svc):
        with patch("circuitai.services.lab_service.HAS_ANTHROPIC", False):
            with pytest.raises(Exception, match="anthropic"):
                lab_svc.extract_from_pdf_vision("/fake/path.pdf")

    def test_vision_parses_json_response(self, lab_svc):
        """Mock vision API and verify JSON parsing."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='{"patient_name": "Test", "panels": []}')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("circuitai.services.lab_service.HAS_ANTHROPIC", True), \
             patch("circuitai.services.lab_service.HAS_PDFPLUMBER", True), \
             patch("circuitai.services.lab_service.anthropic") as mock_anthropic, \
             patch("circuitai.services.lab_service.pdfplumber") as mock_pdfplumber:

            mock_anthropic.Anthropic.return_value = mock_client

            # Mock PDF pages
            mock_page = MagicMock()
            mock_img = MagicMock()
            mock_page.to_image.return_value = mock_img

            # Create a real temp file for the save
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(b"fake png data")
                temp_path = f.name

            mock_img.save.side_effect = lambda p: Path(p).write_bytes(b"fake")
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdfplumber.open.return_value = mock_pdf

            # Mock API key
            lab_svc.db.execute(
                "INSERT INTO adapter_state (id, adapter_name, key, value) VALUES (?, ?, ?, ?)",
                ("test-key", "capture", "anthropic_api_key", "sk-test"),
            )
            lab_svc.db.commit()

            result = lab_svc.extract_from_pdf_vision("/fake/path.pdf")
            assert result["patient_name"] == "Test"

    def test_vision_handles_json_wrapping(self, lab_svc):
        """Verify ```json wrapping is stripped."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text='```json\n{"patient_name": "Test", "panels": []}\n```')]

        mock_client = MagicMock()
        mock_client.messages.create.return_value = mock_response

        with patch("circuitai.services.lab_service.HAS_ANTHROPIC", True), \
             patch("circuitai.services.lab_service.HAS_PDFPLUMBER", True), \
             patch("circuitai.services.lab_service.anthropic") as mock_anthropic, \
             patch("circuitai.services.lab_service.pdfplumber") as mock_pdfplumber:

            mock_anthropic.Anthropic.return_value = mock_client

            mock_page = MagicMock()
            mock_img = MagicMock()
            mock_page.to_image.return_value = mock_img
            mock_img.save.side_effect = lambda p: Path(p).write_bytes(b"fake")
            mock_pdf = MagicMock()
            mock_pdf.pages = [mock_page]
            mock_pdfplumber.open.return_value = mock_pdf

            lab_svc.db.execute(
                "INSERT OR IGNORE INTO adapter_state (id, adapter_name, key, value) VALUES (?, ?, ?, ?)",
                ("test-key", "capture", "anthropic_api_key", "sk-test"),
            )
            lab_svc.db.commit()

            result = lab_svc.extract_from_pdf_vision("/fake/path.pdf")
            assert result["patient_name"] == "Test"


# ── Service CRUD tests ────────────────────────────────────────


class TestLabServiceCrud:
    def test_list_results(self, lab_svc):
        _seed_full_result(lab_svc)
        results = lab_svc.list_results()
        assert len(results) == 1

    def test_get_result_detail(self, lab_svc):
        result = _seed_full_result(lab_svc)
        detail = lab_svc.get_result_detail(result["result_id"])
        assert detail["result"].patient_name == "John Patel"
        assert len(detail["panels"]) == 2
        # CBC panel should have 2 markers
        cbc_panel = next(p for p in detail["panels"] if p["panel"].panel_name == "Complete Blood Count")
        assert len(cbc_panel["markers"]) == 2

    def test_mark_reviewed(self, lab_svc):
        result = _seed_full_result(lab_svc)
        reviewed = lab_svc.mark_reviewed(result["result_id"])
        assert reviewed.status == "reviewed"

    def test_get_summary(self, lab_svc):
        _seed_full_result(lab_svc)
        summary = lab_svc.get_summary()
        assert summary["total_results"] == 1
        assert summary["unreviewed_count"] == 1
        assert summary["flagged_marker_count"] == 2

    def test_soft_delete(self, lab_svc):
        result = _seed_full_result(lab_svc)
        lab_svc.delete_result(result["result_id"])
        # Should not appear in active list
        results = lab_svc.list_results()
        assert len(results) == 0
        # Should appear with show_all
        all_results = lab_svc.list_results(active_only=False)
        assert len(all_results) == 1

    def test_get_flagged_markers_for_result(self, lab_svc):
        result = _seed_full_result(lab_svc)
        flagged = lab_svc.get_flagged_markers(result["result_id"])
        assert len(flagged) == 2
        for m in flagged:
            assert m.flag in ("high", "low", "critical")


# ── Trends tests ─────────────────────────────────────────────


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
                    {"marker_name": "HDL", "value": "50", "unit": "mg/dL",
                     "reference_low": "40", "reference_high": "", "flag": "normal"},
                ],
            }],
        }
        lab_svc.import_lab_data(data, source="pdf")


class TestMarkerHistory:
    def test_get_marker_history(self, lab_svc):
        _seed_multi_date_results(lab_svc)
        history = lab_svc.markers.get_marker_history("Cholesterol, Total")
        assert len(history) == 3
        # Ordered by date ASC
        assert history[0]["result_date"] == "2024-01-15"
        assert history[0]["value"] == "180"
        assert history[2]["result_date"] == "2025-01-10"
        assert history[2]["value"] == "165"

    def test_get_marker_history_empty(self, lab_svc):
        history = lab_svc.markers.get_marker_history("Nonexistent Marker")
        assert history == []

    def test_list_distinct_names(self, lab_svc):
        _seed_multi_date_results(lab_svc)
        names = lab_svc.markers.list_distinct_names()
        assert "Cholesterol, Total" in names
        assert "HDL" in names
        # Should be alphabetically sorted
        assert names == sorted(names)

    def test_list_distinct_names_empty(self, lab_svc):
        names = lab_svc.markers.list_distinct_names()
        assert names == []

    def test_excludes_inactive_results(self, lab_svc):
        _seed_multi_date_results(lab_svc)
        results = lab_svc.list_results()
        # Delete the first result
        lab_svc.delete_result(results[-1].id)
        history = lab_svc.markers.get_marker_history("Cholesterol, Total")
        assert len(history) == 2


class TestMarkerTrends:
    def test_get_marker_trends(self, lab_svc):
        _seed_multi_date_results(lab_svc)
        trends = lab_svc.get_marker_trends("Cholesterol, Total")
        assert trends["marker_name"] == "Cholesterol, Total"
        assert trends["unit"] == "mg/dL"
        assert trends["count"] == 3
        assert len(trends["data_points"]) == 3

    def test_trends_change_calculation(self, lab_svc):
        _seed_multi_date_results(lab_svc)
        trends = lab_svc.get_marker_trends("Cholesterol, Total")
        pts = trends["data_points"]
        # First point has no change
        assert pts[0]["change"] is None
        # Second: 205 - 180 = 25
        assert pts[1]["change"] == 25.0
        # Third: 165 - 205 = -40
        assert pts[2]["change"] == -40.0

    def test_trends_change_pct(self, lab_svc):
        _seed_multi_date_results(lab_svc)
        trends = lab_svc.get_marker_trends("Cholesterol, Total")
        pts = trends["data_points"]
        # 25/180 * 100 ≈ 13.89%
        assert pts[1]["change_pct"] == pytest.approx(13.889, abs=0.01)

    def test_trends_empty(self, lab_svc):
        trends = lab_svc.get_marker_trends("Nonexistent")
        assert trends["count"] == 0
        assert trends["data_points"] == []

    def test_list_marker_names(self, lab_svc):
        _seed_multi_date_results(lab_svc)
        names = lab_svc.list_marker_names()
        assert "Cholesterol, Total" in names
        assert "HDL" in names


class TestTrendsCli:
    def _invoke(self, args, db):
        from circuitai.cli.main import cli, CircuitContext

        runner = CliRunner()
        with patch.object(CircuitContext, "get_db", return_value=db):
            return runner.invoke(cli, ["health"] + args, catch_exceptions=False)

    def test_trends_with_marker_name(self, db, lab_svc):
        _seed_multi_date_results(lab_svc)
        result = self._invoke(["trends", "Cholesterol, Total"], db)
        assert result.exit_code == 0
        assert "Cholesterol, Total" in result.output
        assert "180" in result.output
        assert "205" in result.output
        assert "165" in result.output

    def test_trends_json_output(self, db, lab_svc):
        _seed_multi_date_results(lab_svc)
        result = self._invoke(["--json", "trends", "Cholesterol, Total"], db)
        assert result.exit_code == 0
        import json
        envelope = json.loads(result.output)
        data = envelope["data"]
        assert data["marker_name"] == "Cholesterol, Total"
        assert data["count"] == 3
        assert len(data["data_points"]) == 3

    def test_trends_empty_marker(self, db, lab_svc):
        _seed_multi_date_results(lab_svc)
        result = self._invoke(["trends", "Nonexistent Marker"], db)
        assert result.exit_code == 0
        assert "No data found" in result.output

    def test_trends_no_data_at_all(self, db):
        result = self._invoke(["trends", "WBC"], db)
        assert result.exit_code == 0
        assert "No data found" in result.output

    def test_trends_json_requires_argument(self, db, lab_svc):
        _seed_multi_date_results(lab_svc)
        result = self._invoke(["--json", "trends"], db)
        assert result.exit_code == 0
        assert "required" in result.output.lower() or "error" in result.output.lower()

    def test_trends_shows_change_indicators(self, db, lab_svc):
        _seed_multi_date_results(lab_svc)
        result = self._invoke(["trends", "Cholesterol, Total"], db)
        assert result.exit_code == 0
        # Should have +25 and -40 changes
        assert "+25" in result.output
        assert "-40" in result.output

    def test_trends_shows_summary_footer(self, db, lab_svc):
        _seed_multi_date_results(lab_svc)
        result = self._invoke(["trends", "Cholesterol, Total"], db)
        assert result.exit_code == 0
        assert "3 data points" in result.output
        assert "Range:" in result.output
        assert "Latest:" in result.output


# ── CLI tests ─────────────────────────────────────────────────


class TestHealthCli:
    def _invoke(self, args, db):
        from circuitai.cli.main import cli, CircuitContext

        runner = CliRunner()
        # Patch get_db to use our test DB
        with patch.object(CircuitContext, "get_db", return_value=db):
            return runner.invoke(cli, ["health"] + args, catch_exceptions=False)

    def test_health_list_empty(self, db):
        result = self._invoke(["list"], db)
        assert result.exit_code == 0
        assert "No lab results" in result.output

    def test_health_list_json_empty(self, db):
        result = self._invoke(["--json", "list"], db)
        assert result.exit_code == 0
        assert "[]" in result.output

    def test_health_list_with_data(self, db, lab_svc):
        _seed_full_result(lab_svc)
        result = self._invoke(["list"], db)
        assert result.exit_code == 0
        assert "LabCorp" in result.output

    def test_health_list_json_with_data(self, db, lab_svc):
        _seed_full_result(lab_svc)
        result = self._invoke(["--json", "list"], db)
        assert result.exit_code == 0
        assert "LabCorp" in result.output

    def test_health_summary_empty(self, db):
        result = self._invoke(["summary"], db)
        assert result.exit_code == 0
        assert "Total lab results: 0" in result.output

    def test_health_summary_with_data(self, db, lab_svc):
        _seed_full_result(lab_svc)
        result = self._invoke(["summary"], db)
        assert result.exit_code == 0
        assert "Total lab results: 1" in result.output
        assert "Flagged markers: 2" in result.output

    def test_health_summary_json(self, db, lab_svc):
        _seed_full_result(lab_svc)
        result = self._invoke(["--json", "summary"], db)
        assert result.exit_code == 0
        assert '"total_results"' in result.output

    def test_health_flagged_empty(self, db):
        result = self._invoke(["flagged"], db)
        assert result.exit_code == 0
        assert "No flagged markers" in result.output

    def test_health_flagged_with_data(self, db, lab_svc):
        _seed_full_result(lab_svc)
        result = self._invoke(["flagged"], db)
        assert result.exit_code == 0
        assert "Cholesterol" in result.output

    def test_health_flagged_json(self, db, lab_svc):
        _seed_full_result(lab_svc)
        result = self._invoke(["--json", "flagged"], db)
        assert result.exit_code == 0
        assert "Cholesterol" in result.output


# ── LabCorp site adapter tests ────────────────────────────────


class TestLabCorpSite:
    def test_registration(self):
        from circuitai.services.sites import get_site
        site_cls = get_site("labcorp")
        assert site_cls.DISPLAY_NAME == "LabCorp Patient Portal"
        assert site_cls.DOMAIN == "patient.labcorp.com"

    def test_class_attributes(self):
        from circuitai.services.sites.labcorp import LabCorpSite
        assert LabCorpSite.BILL_CATEGORY == "healthcare"

    def test_login_fills_form(self):
        from circuitai.services.sites.labcorp import LabCorpSite

        mock_page = MagicMock()
        mock_svc = MagicMock()

        # Mock visible elements for: cookie button, sign-in link, form fields
        mock_el = MagicMock()
        mock_el.is_visible.return_value = True

        # query_selector returns mock_el for all selectors
        mock_page.query_selector.return_value = mock_el
        # query_selector_all returns [mock_el] for Sign In link search
        mock_page.query_selector_all.return_value = [mock_el]
        # No iframe — login_frame falls back to main page
        mock_page.frames = []
        # After login, URL no longer contains 'login'
        mock_page.url = "https://patient.labcorp.com/results"

        site = LabCorpSite(mock_page, mock_svc)
        with patch.object(site, "needs_2fa", return_value=False):
            result = site.login("test@example.com", "password123")

        # Verify navigation happened
        mock_page.goto.assert_called_once()
        # Verify form was filled (username + password = 2 fill calls)
        assert mock_el.fill.call_count >= 2
        assert result is True

    def test_needs_2fa_false(self):
        from circuitai.services.sites.labcorp import LabCorpSite

        mock_page = MagicMock()
        mock_page.query_selector.return_value = None
        mock_svc = MagicMock()

        site = LabCorpSite(mock_page, mock_svc)
        assert site.needs_2fa() is False

    def test_needs_2fa_true(self):
        from circuitai.services.sites.labcorp import LabCorpSite

        mock_page = MagicMock()
        # First call returns None, second call returns an element (verification code text)
        mock_el = MagicMock()
        mock_page.query_selector.side_effect = [None, mock_el, None, None, None, None, None, None]
        mock_svc = MagicMock()

        site = LabCorpSite(mock_page, mock_svc)
        assert site.needs_2fa() is True

    def test_extract_empty_dom(self):
        from circuitai.services.sites.labcorp import LabCorpSite

        mock_page = MagicMock()
        mock_page.query_selector_all.return_value = []
        mock_svc = MagicMock()
        mock_svc.db = MagicMock()

        # Make capture service not configured to skip vision fallback
        with patch("circuitai.services.sites.labcorp.LabCorpSite._extract_via_vision") as mock_vision:
            mock_vision.return_value = {
                "data_type": "lab_results",
                "account_name": "LabCorp",
                "results": [],
            }
            site = LabCorpSite(mock_page, mock_svc)
            result = site.extract_billing()
            assert result["data_type"] == "lab_results"

    def test_list_sites_includes_labcorp(self):
        from circuitai.services.sites import list_sites
        sites = list_sites()
        keys = [s["key"] for s in sites]
        assert "labcorp" in keys

    def test_normalize_date(self):
        from circuitai.services.sites.labcorp import LabCorpSite
        assert LabCorpSite._normalize_date("02/15/2026") == "2026-02-15"
        assert LabCorpSite._normalize_date("2-5-26") == "2026-02-05"


# ── Morning briefing integration ──────────────────────────────


class TestMorningIntegration:
    def test_morning_includes_lab_results(self, db, lab_svc):
        _seed_full_result(lab_svc)

        from circuitai.services.morning_service import MorningService
        morning = MorningService(db)
        briefing = morning.get_briefing()

        lab_items = [i for i in briefing["attention_items"] if i["type"] == "lab_unreviewed"]
        assert len(lab_items) == 1
        assert lab_items[0]["flagged_count"] == 2

    def test_morning_flagged_marker_count(self, db, lab_svc):
        _seed_full_result(lab_svc)

        from circuitai.services.morning_service import MorningService
        morning = MorningService(db)
        briefing = morning.get_briefing()

        assert briefing["week_summary"]["health_flagged_markers"] == 2

    def test_morning_no_lab_after_review(self, db, lab_svc):
        result = _seed_full_result(lab_svc)
        lab_svc.mark_reviewed(result["result_id"])

        from circuitai.services.morning_service import MorningService
        morning = MorningService(db)
        briefing = morning.get_briefing()

        lab_items = [i for i in briefing["attention_items"] if i["type"] == "lab_unreviewed"]
        assert len(lab_items) == 0
        assert briefing["week_summary"]["health_flagged_markers"] == 0
