"""Lab results service — import from PDF, extract via text/vision, CRUD operations."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.core.exceptions import AdapterError, NotFoundError
from circuitai.models.base import new_id, now_iso
from circuitai.models.lab import (
    LabMarker,
    LabMarkerRepository,
    LabPanel,
    LabPanelRepository,
    LabResult,
    LabResultRepository,
)

try:
    import anthropic

    HAS_ANTHROPIC = True
except ImportError:
    HAS_ANTHROPIC = False

try:
    import pdfplumber

    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False


def compute_lab_fingerprint(result_date: str, provider: str, patient_name: str) -> str:
    """Compute a deterministic fingerprint for lab report dedup.

    Same pattern as compute_txn_fingerprint: normalize to uppercase alphanumeric, SHA-256[:16].
    """
    normalized_provider = re.sub(r"[^A-Z0-9]", "", provider.upper())
    normalized_name = re.sub(r"[^A-Z0-9]", "", patient_name.upper())
    raw = f"{result_date}|{normalized_provider}|{normalized_name}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


_LAB_VISION_PROMPT = """\
You are extracting lab test results from a medical lab report image.

Return ONLY valid JSON (no markdown fences) with this structure:
{
  "patient_name": "string",
  "provider": "string (e.g. LabCorp, Quest Diagnostics)",
  "ordering_physician": "string",
  "order_date": "YYYY-MM-DD or null",
  "result_date": "YYYY-MM-DD or null",
  "panels": [
    {
      "panel_name": "string (e.g. Complete Blood Count, Lipid Panel)",
      "markers": [
        {
          "marker_name": "string",
          "value": "string",
          "unit": "string",
          "reference_low": "string or empty",
          "reference_high": "string or empty",
          "flag": "normal | low | high | critical"
        }
      ]
    }
  ]
}

Rules:
- Values and reference ranges are TEXT (they can be ">= 40", "< 0.5", "Reactive", etc.)
- flag should be "high" if marked H, "low" if marked L, "critical" if marked A or C, otherwise "normal"
- Dates as YYYY-MM-DD
- If a field is unknown, use null or empty string
- Group markers under their panel headers
"""


# Date patterns
_DATE_RE = re.compile(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})")

# Provider detection
_PROVIDERS = {
    "labcorp": "LabCorp",
    "quest": "Quest Diagnostics",
    "bioreference": "BioReference",
}

# Generic marker regex (non-LabCorp PDFs)
_GENERIC_MARKER_RE = re.compile(
    r"^([A-Za-z][\w\s/(),.-]+?)\s{2,}"
    r"([\d.<>]+\S*)\s+"
    r"(\S+)\s+"
    r"([\d.<>]+)\s*[-–]\s*([\d.<>]+)"
    r"(?:\s+([HLAChlac]))?",
    re.MULTILINE,
)

# LabCorp panel header: line that appears before the "Test Current Result..." header
# Detected as a line that is NOT a marker row AND is followed by the header line
_LABCORP_HEADER_LINE = "Test Current Result and Flag"

# Generic panel header patterns (all-caps lines)
_PANEL_HEADER_RE = re.compile(r"^([A-Z][A-Z\s&/()-]{3,})(?:\s*:?\s*)$", re.MULTILINE)


class LabService:
    """Lab results import, extraction, and management."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db
        self.results = LabResultRepository(db)
        self.panels = LabPanelRepository(db)
        self.markers = LabMarkerRepository(db)

    # ── Fingerprint & dedup ───────────────────────────────────────

    def _check_duplicate(self, fingerprint: str) -> LabResult | None:
        return self.results.find_by_fingerprint(fingerprint)

    # ── PDF text extraction ───────────────────────────────────────

    def extract_from_pdf_text(self, text: str) -> dict[str, Any]:
        """Parse lab result data from raw PDF text using regex patterns."""
        data: dict[str, Any] = {
            "patient_name": "",
            "provider": "",
            "ordering_physician": "",
            "order_date": None,
            "result_date": None,
            "panels": [],
        }

        if not text.strip():
            return data

        # Provider (check first to select format-specific logic)
        text_lower = text.lower()
        for key, name in _PROVIDERS.items():
            if key in text_lower:
                data["provider"] = name
                break

        is_labcorp = data["provider"] == "LabCorp"

        # Patient name — LabCorp format: "LastName, FirstName M DOB Patient Report"
        if is_labcorp:
            name_match = re.search(
                r"^([A-Za-z]+,\s*[A-Za-z]+(?:\s+[A-Z])?)\s+\d{2}/\d{2}/\d{4}\s+Patient Report",
                text,
                re.MULTILINE,
            )
            if name_match:
                raw_name = name_match.group(1).strip()
                # Convert "LastName, FirstName M" to "FirstName LastName"
                parts = raw_name.split(",", 1)
                if len(parts) == 2:
                    last = parts[0].strip().title()
                    first_middle = parts[1].strip().title()
                    # Remove single-letter middle initial
                    first = first_middle.split()[0] if first_middle else ""
                    data["patient_name"] = f"{first} {last}"
                else:
                    data["patient_name"] = raw_name.title()
        else:
            name_match = re.search(
                r"(?:Patient\s*(?:Name)?|Name)\s*[:]\s*(.+?)(?:\n|$)",
                text,
                re.IGNORECASE,
            )
            if name_match:
                data["patient_name"] = name_match.group(1).strip()

        # Ordering physician
        phys_match = re.search(
            r"(?:Ordering\s*Physician|Physician|Doctor|Ordered\s*[Bb]y)\s*[:]\s*(.+?)(?:\n|$)",
            text,
            re.IGNORECASE,
        )
        if phys_match:
            data["ordering_physician"] = phys_match.group(1).strip()

        # Dates
        date_collected = re.search(
            r"(?:Date\s*(?:Collected|Drawn|Ordered))\s*[:]\s*(.+?)(?:\n|$)",
            text,
            re.IGNORECASE,
        )
        date_reported = re.search(
            r"(?:Date\s*(?:Reported|Resulted|Received))\s*[:]\s*(.+?)(?:\n|$)",
            text,
            re.IGNORECASE,
        )

        if date_collected:
            data["order_date"] = self._normalize_date(date_collected.group(1).strip())
        if date_reported:
            data["result_date"] = self._normalize_date(date_reported.group(1).strip())

        # Extract markers and group into panels
        if is_labcorp:
            panels = self._extract_labcorp_panels(text)
        else:
            panels = self._extract_generic_panels(text)
        data["panels"] = panels

        return data

    def _extract_labcorp_panels(self, text: str) -> list[dict[str, Any]]:
        """Extract panels and markers from LabCorp PDF format.

        LabCorp format: panel header line, then "Test Current Result and Flag..." header,
        then marker rows with: MarkerName [01]? Value [PrevValue PrevDate] Unit RefRange [Flag]
        """
        lines = text.split("\n")
        panels: list[dict[str, Any]] = []
        current_panel_name: str | None = None
        current_markers: list[dict[str, Any]] = []
        in_marker_section = False
        # Track lines to identify panel headers (line before "Test Current Result...")
        prev_line = ""

        # Lines to skip (startswith patterns)
        skip_starts = [
            "Patient Report", "Date Created and Stored", "©", "All Rights Reserved",
            "Please Note:", "Microscopic follows", "Microscopic was indicated",
            "Clinical Info:", "General Comments", "Ordered Items:",
            "Icon Legend", "Out of Reference", "Performing Labs",
            "Patient Details", "Physician Details", "Specimen Details",
            "Historical Results", "The Previous Result",
            "Prediabetes:", "Diabetes:", "Glycemic control",
            "Roche ECLIA", "According to", "decrease and remain",
            "prostatectomy", "Values obtained", "interchangeably",
            "Normal:", "Moderately increased", "Severely increased",
            "Men Women", "Avg.Risk", "Performed",
            "Previous Result",
        ]

        for line in lines:
            stripped = line.strip()
            if not stripped:
                prev_line = ""
                continue

            # Check for header line BEFORE skip patterns (header contains "Previous Result")
            if _LABCORP_HEADER_LINE in stripped:
                if current_markers and current_panel_name:
                    panels.append({"panel_name": current_panel_name, "markers": current_markers})
                    current_markers = []
                if prev_line and not prev_line.startswith("Date Collected"):
                    current_panel_name = prev_line.strip()
                    current_panel_name = re.sub(r"\s*\(Cont\.\)\s*$", "", current_panel_name)
                else:
                    current_panel_name = "General"
                in_marker_section = True
                prev_line = stripped
                continue

            # Skip header/footer/note lines
            if any(stripped.startswith(p) for p in skip_starts):
                prev_line = stripped
                continue

            # Skip repeated patient header lines
            if re.match(r"^[A-Za-z]+,\s*[A-Za-z]+.*Patient Report", stripped):
                prev_line = stripped
                continue
            if re.match(r"^(Patient ID|Specimen ID|DOB|Date Collected):", stripped):
                prev_line = stripped
                continue

            # If in marker section, try to parse marker rows
            if in_marker_section:
                marker = self._parse_labcorp_marker_line(stripped)
                if marker:
                    current_markers.append(marker)
                elif not stripped[0].isdigit() and len(stripped) > 3:
                    # Could be a sub-header or continuation panel name
                    # Check if next line might be "Test Current Result..."
                    pass

            prev_line = stripped

        # Save last panel
        if current_markers and current_panel_name:
            panels.append({"panel_name": current_panel_name, "markers": current_markers})

        return panels

    def _parse_labcorp_marker_line(self, line: str) -> dict[str, Any] | None:
        """Parse a single LabCorp marker row.

        Strategy: Split on the previous-result date (MM/DD/YYYY), which consistently
        separates marker-name+value from unit+reference. Then parse each side.

        Formats:
            WBC 01 4.8 5.7 11/14/2024 x10E3/uL 3.4-10.8
            eGFR 113 108 11/14/2024 mL/min/1.73 >59
            BUN/Creatinine Ratio 13 12 11/14/2024 9-20
            Specific Gravity 01 1.009 1.015 11/14/2024 1.005-1.030
            Urine-Color 01 Yellow Yellow 11/14/2024 Yellow
        """
        if line.startswith("*") or line.startswith("†"):
            return None

        # Split on the previous-result date pattern (MM/DD/YYYY)
        date_split = re.split(r"\s+\d{1,2}/\d{1,2}/\d{4}\s+", line, maxsplit=1)
        if len(date_split) != 2:
            return None

        left = date_split[0].strip()   # "WBC 01 4.8 5.7" or "eGFR 113 108"
        right = date_split[1].strip()  # "x10E3/uL 3.4-10.8" or "mL/min/1.73 >59" or "9-20"

        # Parse left side: marker_name [01] current_value [previous_value]
        # Remove lab code "01" if present
        left = re.sub(r"\s+01\s+", " ", left)

        # Split tokens: last 1-2 are numeric values, rest is marker name
        tokens = left.split()
        if len(tokens) < 2:
            return None

        # Work backwards: find where numbers start
        value_start = len(tokens)
        for i in range(len(tokens) - 1, 0, -1):
            # Check if this token looks like a value (number, <, >, or lab qualitative)
            if re.match(r"^[\d.<>]+\S*$", tokens[i]) or tokens[i] in ("Negative", "Positive", "Reactive"):
                value_start = i
            else:
                break

        if value_start >= len(tokens):
            return None

        marker_name = " ".join(tokens[:value_start]).strip()
        current_value = tokens[value_start]  # First numeric token = current value

        if not marker_name or self._is_noise_line(marker_name):
            return None

        # Parse right side: [unit] reference_range [flag]
        unit, ref_low, ref_high, flag = self._parse_labcorp_right_side(right)

        return {
            "marker_name": marker_name,
            "value": current_value,
            "unit": unit,
            "reference_low": ref_low,
            "reference_high": ref_high,
            "flag": self._parse_flag(flag),
        }

    def _parse_labcorp_right_side(self, text: str) -> tuple[str, str, str, str]:
        """Parse the right side after the date: unit + reference + optional flag.

        Examples:
            "x10E3/uL 3.4-10.8"      -> ("x10E3/uL", "3.4", "10.8", "")
            "mL/min/1.73 >59"         -> ("mL/min/1.73", "59", "", "")
            "mg/dL 100-199"           -> ("mg/dL", "100", "199", "")
            "9-20"                    -> ("", "9", "20", "")
            "% Not Estab."            -> ("%", "", "", "")
            "Negative"                -> ("", "", "", "")
            "mg/dL 0.0-1.2"          -> ("mg/dL", "0.0", "1.2", "")
            "mg/dL 100-199 H"        -> ("mg/dL", "100", "199", "H")
        """
        parts = text.split()
        if not parts:
            return ("", "", "", "")

        unit = ""
        ref_low = ""
        ref_high = ""
        flag = ""

        # Check for trailing flag (single char H/L/A/C)
        if parts and re.match(r"^[HLAChlac*]$", parts[-1]):
            flag = parts[-1].upper().replace("*", "")
            parts = parts[:-1]

        if not parts:
            return (unit, ref_low, ref_high, flag)

        # Check if "Not Estab." is the reference
        joined = " ".join(parts)
        if "Not Estab" in joined or "Negative" in joined or "None seen" in joined:
            # Find the unit before "Not Estab."
            for i, p in enumerate(parts):
                if p.startswith("Not") or p == "Negative" or p == "None":
                    unit = " ".join(parts[:i])
                    break
            return (unit, "", "", flag)

        # Look for range pattern "low-high" in the parts
        for i, p in enumerate(parts):
            range_match = re.match(r"^([\d.]+)[-–]([\d.]+)$", p)
            if range_match:
                ref_low = range_match.group(1)
                ref_high = range_match.group(2)
                unit = " ".join(parts[:i])
                break
            # Check for ">59" or ">=40" type reference
            gt_match = re.match(r"^[><]=?\s*([\d.]+)$", p)
            if gt_match:
                if p.startswith(">"):
                    ref_low = gt_match.group(1)
                else:
                    ref_high = gt_match.group(1)
                unit = " ".join(parts[:i])
                break

        return (unit, ref_low, ref_high, flag)

    @staticmethod
    def _is_noise_line(name: str) -> bool:
        """Filter out lines that look like marker names but aren't."""
        noise = {
            "test current", "date created", "date collected", "date reported",
            "date received", "patient id", "specimen id", "ref.", "units",
        }
        return name.lower() in noise or len(name) < 2

    def _extract_generic_panels(self, text: str) -> list[dict[str, Any]]:
        """Extract panels from non-LabCorp PDFs using generic regex."""
        lines = text.split("\n")
        panels: list[dict[str, Any]] = []
        current_panel_name = "General"
        current_markers: list[dict[str, Any]] = []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue

            # Check for panel header (all-caps)
            header_match = _PANEL_HEADER_RE.match(stripped)
            if header_match and not _GENERIC_MARKER_RE.match(stripped):
                if current_markers:
                    panels.append({"panel_name": current_panel_name, "markers": current_markers})
                    current_markers = []
                current_panel_name = header_match.group(1).strip().title()
                continue

            # Try generic marker pattern
            marker_match = _GENERIC_MARKER_RE.match(stripped)
            if marker_match:
                flag_raw = (marker_match.group(6) or "").upper()
                current_markers.append({
                    "marker_name": marker_match.group(1).strip(),
                    "value": marker_match.group(2),
                    "unit": marker_match.group(3),
                    "reference_low": marker_match.group(4),
                    "reference_high": marker_match.group(5),
                    "flag": self._parse_flag(flag_raw),
                })

        if current_markers:
            panels.append({"panel_name": current_panel_name, "markers": current_markers})

        return panels

    @staticmethod
    def _parse_flag(flag_char: str) -> str:
        if flag_char in ("H",):
            return "high"
        if flag_char in ("L",):
            return "low"
        if flag_char in ("A", "C"):
            return "critical"
        return "normal"

    @staticmethod
    def _normalize_date(text: str) -> str | None:
        """Normalize date text to YYYY-MM-DD."""
        match = _DATE_RE.search(text)
        if not match:
            return None
        month, day, year = match.groups()
        if len(year) == 2:
            year = f"20{year}"
        return f"{year}-{int(month):02d}-{int(day):02d}"

    # ── Vision API extraction ─────────────────────────────────────

    def extract_from_pdf_vision(self, pdf_path: str) -> dict[str, Any]:
        """Extract lab data from PDF using Claude vision API on page images."""
        if not HAS_ANTHROPIC:
            raise AdapterError("anthropic package not installed. Install with: pip install anthropic")

        if not HAS_PDFPLUMBER:
            raise AdapterError("pdfplumber package not installed. Install with: pip install pdfplumber")

        api_key = self._get_api_key()
        if not api_key:
            raise AdapterError("Anthropic API key not configured. Run 'circuit capture setup' first.")

        pdf = pdfplumber.open(pdf_path)
        image_contents = []

        for page in pdf.pages:
            img = page.to_image(resolution=200)
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                img.save(f.name)
                image_data = base64.b64encode(Path(f.name).read_bytes()).decode("utf-8")
                Path(f.name).unlink(missing_ok=True)

            image_contents.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_data,
                },
            })

        pdf.close()

        if not image_contents:
            return {"panels": []}

        # Send all pages to Claude
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": image_contents + [{
                    "type": "text",
                    "text": _LAB_VISION_PROMPT,
                }],
            }],
        )

        raw = message.content[0].text.strip()
        # Handle ```json wrapping
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise AdapterError(f"Vision API returned invalid JSON: {e}\nRaw: {raw[:200]}") from e

    def _get_api_key(self) -> str | None:
        """Get Anthropic API key from adapter_state."""
        row = self.db.fetchone(
            "SELECT value FROM adapter_state WHERE adapter_name = 'capture' AND key = 'anthropic_api_key'",
        )
        return row["value"] if row else None

    # ── Import orchestrator ───────────────────────────────────────

    def import_from_pdf(self, file_path: str) -> dict[str, Any]:
        """Full PDF import: text extraction → vision fallback → fingerprint → persist."""
        if not HAS_PDFPLUMBER:
            raise AdapterError("pdfplumber package not installed. Install with: pip install pdfplumber")

        pdf = pdfplumber.open(file_path)
        full_text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        pdf.close()

        # Try text extraction first
        parsed = self.extract_from_pdf_text(full_text)
        has_markers = any(p.get("markers") for p in parsed.get("panels", []))

        # Vision fallback if text extraction is incomplete
        if not has_markers and HAS_ANTHROPIC:
            try:
                api_key = self._get_api_key()
                if api_key:
                    parsed = self.extract_from_pdf_vision(file_path)
            except Exception:
                pass  # Fall through with text results

        # Compute fingerprint for dedup
        result_date = parsed.get("result_date") or ""
        provider = parsed.get("provider") or ""
        patient_name = parsed.get("patient_name") or ""

        if result_date and provider:
            fingerprint = compute_lab_fingerprint(result_date, provider, patient_name)
            existing = self._check_duplicate(fingerprint)
            if existing:
                return {
                    "result_id": existing.id,
                    "panels_imported": 0,
                    "markers_imported": 0,
                    "flagged_count": 0,
                    "duplicate": True,
                    "existing_date": existing.created_at,
                }
        else:
            fingerprint = None

        parsed["report_fingerprint"] = fingerprint
        result = self.import_lab_data(parsed, source="pdf")
        result["duplicate"] = False
        return result

    def import_lab_data(self, data: dict[str, Any], source: str = "pdf") -> dict[str, Any]:
        """Persist parsed lab data into the 3-table hierarchy."""
        # Compute fingerprint for dedup if not already set
        fingerprint = data.get("report_fingerprint")
        if not fingerprint:
            fingerprint = compute_lab_fingerprint(
                data.get("result_date", ""),
                data.get("provider", ""),
                data.get("patient_name", ""),
            )

        # Check for duplicates
        existing = self.results.find_by_fingerprint(fingerprint)
        if existing:
            return {
                "result_id": existing.id,
                "panels_imported": 0,
                "markers_imported": 0,
                "flagged_count": 0,
                "duplicate": True,
            }

        # Create LabResult
        lab_result = LabResult(
            patient_name=data.get("patient_name", ""),
            provider=data.get("provider", ""),
            ordering_physician=data.get("ordering_physician", ""),
            order_date=data.get("order_date"),
            result_date=data.get("result_date"),
            report_fingerprint=fingerprint,
            status="completed",
            source=source,
        )
        self.results.insert(lab_result)

        panels_imported = 0
        markers_imported = 0
        flagged_count = 0

        for panel_data in data.get("panels", []):
            panel_name = panel_data.get("panel_name", "General")
            markers = panel_data.get("markers", [])

            # Determine panel status from markers
            panel_status = "normal"
            for m in markers:
                flag = m.get("flag", "normal")
                if flag == "critical":
                    panel_status = "critical"
                    break
                if flag in ("high", "low"):
                    panel_status = "abnormal"

            panel = LabPanel(
                lab_result_id=lab_result.id,
                panel_name=panel_name,
                status=panel_status,
            )
            self.panels.insert(panel)
            panels_imported += 1

            for m in markers:
                marker = LabMarker(
                    lab_panel_id=panel.id,
                    marker_name=m.get("marker_name", ""),
                    value=m.get("value", ""),
                    unit=m.get("unit", ""),
                    reference_low=m.get("reference_low", ""),
                    reference_high=m.get("reference_high", ""),
                    flag=m.get("flag", "normal"),
                )
                self.markers.insert(marker)
                markers_imported += 1
                if marker.is_flagged:
                    flagged_count += 1

        return {
            "result_id": lab_result.id,
            "panels_imported": panels_imported,
            "markers_imported": markers_imported,
            "flagged_count": flagged_count,
            "duplicate": False,
        }

    # ── CRUD ──────────────────────────────────────────────────────

    def list_results(self, active_only: bool = True) -> list[LabResult]:
        return self.results.list_all(active_only=active_only)

    def get_result(self, result_id: str) -> LabResult:
        return self.results.get(result_id)

    def get_result_detail(self, result_id: str) -> dict[str, Any]:
        """Get a result with all nested panels and markers."""
        result = self.results.get(result_id)
        panels = self.panels.get_for_result(result_id)
        panels_detail = []
        for panel in panels:
            markers = self.markers.get_for_panel(panel.id)
            panels_detail.append({
                "panel": panel,
                "markers": markers,
            })
        return {
            "result": result,
            "panels": panels_detail,
        }

    def get_panels(self, result_id: str) -> list[LabPanel]:
        return self.panels.get_for_result(result_id)

    def get_markers(self, panel_id: str) -> list[LabMarker]:
        return self.markers.get_for_panel(panel_id)

    def get_flagged_markers(self, result_id: str) -> list[LabMarker]:
        return self.markers.get_flagged_for_result(result_id)

    def mark_reviewed(self, result_id: str) -> LabResult:
        return self.results.update(result_id, status="reviewed")

    def delete_result(self, result_id: str) -> None:
        """Soft-delete a lab result."""
        self.results.soft_delete(result_id)

    def get_summary(self) -> dict[str, Any]:
        """Overview stats for health summary."""
        total = self.results.count("is_active = 1")
        unreviewed = self.results.count("is_active = 1 AND status != 'reviewed'")
        flagged = len(self.markers.get_all_flagged())
        recent = self.results.get_recent(limit=5)

        return {
            "total_results": total,
            "unreviewed_count": unreviewed,
            "flagged_marker_count": flagged,
            "recent_results": [r.model_dump() for r in recent],
        }
