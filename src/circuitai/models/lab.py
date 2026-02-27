"""Lab result models and repositories — health tracking hierarchy."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import Field

from circuitai.models.base import BaseRepository, CircuitModel


class LabResult(CircuitModel):
    """A lab report (e.g., blood work from LabCorp)."""

    patient_name: str = ""
    provider: str = ""
    ordering_physician: str = ""
    order_date: str | None = None
    result_date: str | None = None
    report_fingerprint: str | None = None
    status: str = "completed"  # pending, completed, reviewed
    source: str = "pdf"  # pdf, browser, manual
    notes: str = ""
    is_active: bool = True

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data["is_active"] = int(data["is_active"])
        return data

    @classmethod
    def from_row(cls, row: Any) -> "LabResult":
        d = {k: row[k] for k in row.keys()}
        d["is_active"] = bool(d.get("is_active", 1))
        return cls(**d)


class LabPanel(CircuitModel):
    """A panel within a lab result (e.g., Complete Blood Count, Lipid Panel)."""

    lab_result_id: str
    panel_name: str
    status: str = "normal"  # normal, abnormal, critical
    updated_at: str = Field(default="", exclude=True)

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "LabPanel":
        d = {k: row[k] for k in row.keys()}
        d.pop("updated_at", None)
        return cls(**d)


class LabMarker(CircuitModel):
    """An individual marker/test within a panel (e.g., WBC, Cholesterol)."""

    lab_panel_id: str
    marker_name: str
    value: str = ""
    unit: str = ""
    reference_low: str = ""
    reference_high: str = ""
    flag: str = "normal"  # normal, low, high, critical
    updated_at: str = Field(default="", exclude=True)

    @property
    def is_flagged(self) -> bool:
        return self.flag != "normal"

    @property
    def reference_range(self) -> str:
        if self.reference_low and self.reference_high:
            return f"{self.reference_low} - {self.reference_high}"
        if self.reference_low:
            return f">= {self.reference_low}"
        if self.reference_high:
            return f"< {self.reference_high}"
        return ""

    def to_row(self) -> dict[str, Any]:
        data = self.model_dump()
        data.pop("updated_at", None)
        return data

    @classmethod
    def from_row(cls, row: Any) -> "LabMarker":
        d = {k: row[k] for k in row.keys()}
        d.pop("updated_at", None)
        return cls(**d)


class LabResultRepository(BaseRepository):
    table: ClassVar[str] = "lab_results"
    model_class: ClassVar[type[CircuitModel]] = LabResult  # type: ignore[assignment]

    def find_by_fingerprint(self, fingerprint: str) -> LabResult | None:
        row = self.db.fetchone(
            "SELECT * FROM lab_results WHERE report_fingerprint = ? AND is_active = 1",
            (fingerprint,),
        )
        return LabResult.from_row(row) if row else None

    def find_by_status(self, status: str) -> list[LabResult]:
        rows = self.db.fetchall(
            "SELECT * FROM lab_results WHERE status = ? AND is_active = 1 ORDER BY result_date DESC",
            (status,),
        )
        return [LabResult.from_row(r) for r in rows]

    def get_recent(self, limit: int = 10) -> list[LabResult]:
        rows = self.db.fetchall(
            "SELECT * FROM lab_results WHERE is_active = 1 ORDER BY result_date DESC LIMIT ?",
            (limit,),
        )
        return [LabResult.from_row(r) for r in rows]


class LabPanelRepository(BaseRepository):
    table: ClassVar[str] = "lab_panels"
    model_class: ClassVar[type[CircuitModel]] = LabPanel  # type: ignore[assignment]

    def get_for_result(self, lab_result_id: str) -> list[LabPanel]:
        rows = self.db.fetchall(
            "SELECT * FROM lab_panels WHERE lab_result_id = ? ORDER BY panel_name",
            (lab_result_id,),
        )
        return [LabPanel.from_row(r) for r in rows]


class LabMarkerRepository(BaseRepository):
    table: ClassVar[str] = "lab_markers"
    model_class: ClassVar[type[CircuitModel]] = LabMarker  # type: ignore[assignment]

    def get_for_panel(self, lab_panel_id: str) -> list[LabMarker]:
        rows = self.db.fetchall(
            "SELECT * FROM lab_markers WHERE lab_panel_id = ? ORDER BY marker_name",
            (lab_panel_id,),
        )
        return [LabMarker.from_row(r) for r in rows]

    def get_flagged_for_result(self, lab_result_id: str) -> list[LabMarker]:
        """Get all flagged markers across all panels for a result (JOIN)."""
        rows = self.db.fetchall(
            "SELECT m.* FROM lab_markers m "
            "JOIN lab_panels p ON m.lab_panel_id = p.id "
            "WHERE p.lab_result_id = ? AND m.flag != 'normal' "
            "ORDER BY m.marker_name",
            (lab_result_id,),
        )
        return [LabMarker.from_row(r) for r in rows]

    def get_all_flagged(self) -> list[LabMarker]:
        """Get all flagged markers from unreviewed results (for morning briefing)."""
        rows = self.db.fetchall(
            "SELECT m.* FROM lab_markers m "
            "JOIN lab_panels p ON m.lab_panel_id = p.id "
            "JOIN lab_results r ON p.lab_result_id = r.id "
            "WHERE m.flag != 'normal' AND r.status != 'reviewed' AND r.is_active = 1 "
            "ORDER BY r.result_date DESC, m.marker_name",
        )
        return [LabMarker.from_row(r) for r in rows]
