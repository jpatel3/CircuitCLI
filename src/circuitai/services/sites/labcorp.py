"""LabCorp Patient Portal site adapter — login + lab results extraction."""

from __future__ import annotations

import re
from typing import Any

import click

from circuitai.services.sites import register_site
from circuitai.services.sites.base import BaseSite

LOGIN_URL = "https://patient.labcorp.com/"
RESULTS_LIST_URL = "https://patient.labcorp.com/portal/results/list"
API_BASE = "https://portal-api.patient.cws.labcorp.com/protected/patients"
HEADERS_URL = f"{API_BASE}/current/linkedAccounts/results/headers/all"

NAV_TIMEOUT = 30_000
ELEMENT_TIMEOUT = 15_000


@register_site("labcorp")
class LabCorpSite(BaseSite):
    """Browser automation for LabCorp Patient Portal."""

    DISPLAY_NAME = "LabCorp Patient Portal"
    DOMAIN = "patient.labcorp.com"
    BILL_CATEGORY = "healthcare"

    def login(self, username: str, password: str) -> bool:
        """Navigate to LabCorp patient portal and log in.

        LabCorp uses Okta for auth with a multi-step flow:
        1. Landing page → click "Sign In"
        2. Okta iframe: enter email → submit → enter password → submit
        3. Optional 2FA
        """
        import time

        self.page.goto(LOGIN_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
        time.sleep(3)

        # Step 0: Dismiss cookie banner if present
        try:
            cookie_btn = self.page.query_selector('button:has-text("Accept All Cookies")')
            if cookie_btn and cookie_btn.is_visible():
                cookie_btn.click()
                time.sleep(1)
        except Exception:
            pass

        # Step 1: Click "Sign In" on the landing page
        sign_in_clicked = False
        for sel in ['a:has-text("Sign In")', 'button:has-text("Sign In")']:
            els = self.page.query_selector_all(sel)
            for el in els:
                try:
                    if el.is_visible():
                        el.click()
                        sign_in_clicked = True
                        break
                except Exception:
                    continue
            if sign_in_clicked:
                break

        if not sign_in_clicked:
            return False

        time.sleep(3)

        # Step 2: Okta login form — may be in an iframe
        login_frame = self._find_login_frame()

        # Step 2a: Enter email/username
        identifier_filled = False
        identifier_selectors = [
            "input[name='identifier']",
            "input[name='username']",
            "input[type='email']",
            "input[type='text']",
        ]
        for sel in identifier_selectors:
            el = login_frame.query_selector(sel)
            if el and el.is_visible():
                el.fill(username)
                identifier_filled = True
                break

        if not identifier_filled:
            return False

        # Submit identifier (Next button)
        for sel in ["input[type='submit']", "button[type='submit']",
                     "input[value='Next']", "button:has-text('Next')"] :
            el = login_frame.query_selector(sel)
            if el and el.is_visible():
                el.click()
                break

        time.sleep(3)

        # Step 2b: Enter password (second step of Okta flow)
        # Re-find the frame in case it changed
        login_frame = self._find_login_frame()
        password_filled = False
        for sel in ["input[name='credentials.passcode']", "input[name='password']",
                     "input[type='password']"]:
            el = login_frame.query_selector(sel)
            if el and el.is_visible():
                el.fill(password)
                password_filled = True
                break

        if not password_filled:
            return False

        # Submit password (Verify/Sign In button)
        for sel in ["input[type='submit']", "button[type='submit']",
                     "input[value='Verify']", "input[value='Sign in']",
                     "button:has-text('Verify')", "button:has-text('Sign In')"]:
            el = login_frame.query_selector(sel)
            if el and el.is_visible():
                el.click()
                break

        time.sleep(5)

        # Check for 2FA
        if self.needs_2fa():
            return self.handle_2fa()

        return self._verify_logged_in()

    def _find_login_frame(self):
        """Find the Okta login iframe, or fall back to main page."""
        for frame in self.page.frames:
            if "login-patient.labcorp.com" in frame.url or "okta" in frame.url.lower():
                return frame
        return self.page

    def needs_2fa(self) -> bool:
        """Check if the current page shows a 2FA/verification prompt."""
        login_frame = self._find_login_frame()
        twofa_indicators = [
            "text=verification code",
            "text=security code",
            "text=two-factor",
            "text=Verify your identity",
            "text=Enter Code",
            "text=Google Authenticator",
            "input[name='credentials.passcode']",
            "input[name='otpCode']",
            "input[name='verificationCode']",
            "input[name='code']",
            "input[inputmode='numeric']",
        ]
        for sel in twofa_indicators:
            try:
                el = login_frame.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        # Also check main page
        if login_frame != self.page:
            for sel in twofa_indicators:
                try:
                    el = self.page.query_selector(sel)
                    if el:
                        return True
                except Exception:
                    continue
        return False

    def handle_2fa(self) -> bool:
        """Prompt user for 2FA code and enter it."""
        import time

        code = click.prompt("\n  Enter 2FA verification code from Google Authenticator")
        if not code:
            return False

        login_frame = self._find_login_frame()

        code_selectors = [
            "input[name='credentials.passcode']",
            "input[name='otpCode']",
            "input[name='verificationCode']",
            "input[name='code']",
            "input[type='tel']",
            "input[inputmode='numeric']",
        ]
        code_entered = False
        for sel in code_selectors:
            el = login_frame.query_selector(sel)
            if el and el.is_visible():
                el.fill(code.strip())
                code_entered = True
                break

        if not code_entered:
            return False

        # Submit
        for sel in ["input[type='submit']", "button[type='submit']",
                     "input[value='Verify']", "button:has-text('Verify')",
                     "button:has-text('Submit')", "button:has-text('Continue')"]:
            el = login_frame.query_selector(sel)
            if el and el.is_visible():
                el.click()
                break

        time.sleep(5)
        return self._verify_logged_in()

    def needs_captcha(self) -> bool:
        """Check if a CAPTCHA challenge is present."""
        login_frame = self._find_login_frame()
        captcha_indicators = [
            "iframe[src*='captcha']",
            "iframe[src*='recaptcha']",
            "iframe[src*='hcaptcha']",
            "[class*='captcha']",
            "[id*='captcha']",
            "text=Verify you are human",
            "text=complete the challenge",
        ]
        for sel in captcha_indicators:
            try:
                el = login_frame.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        if login_frame != self.page:
            for sel in captcha_indicators:
                try:
                    el = self.page.query_selector(sel)
                    if el:
                        return True
                except Exception:
                    continue
        return False

    def _verify_logged_in(self) -> bool:
        """Check if we're on an authenticated page."""
        logged_in_indicators = [
            "text=Results",
            "text=My Account",
            "text=Sign Out",
            "text=Log Out",
            "a[href*='logout']",
            "a[href*='results']",
        ]
        for sel in logged_in_indicators:
            try:
                el = self.page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue

        current_url = self.page.url.lower()
        if "login" not in current_url and "signin" not in current_url:
            return True

        return False

    def extract_billing(self) -> dict[str, Any]:
        """Extract lab results via LabCorp's internal API.

        Returns data_type='lab_results' to signal the caller to route to LabService.

        Strategy: Use the portal REST API directly (much more reliable than DOM scraping).
        The API provides structured JSON with all marker values, reference ranges, and flags.
        """
        import time

        # Navigate to results page — click the Results nav link to let the SPA
        # properly initialize (direct URL nav may not set up auth tokens).
        results_link = self.page.query_selector('a:has-text("Results")')
        if results_link:
            try:
                results_link.click()
                self.page.wait_for_load_state("networkidle", timeout=ELEMENT_TIMEOUT)
            except Exception:
                pass
        else:
            self.page.goto(RESULTS_LIST_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")
            try:
                self.page.wait_for_load_state("networkidle", timeout=ELEMENT_TIMEOUT)
            except Exception:
                pass
        time.sleep(3)

        # Strategy A: Direct API calls (preferred — structured JSON)
        result = self._extract_via_api()
        if result.get("results"):
            return result

        # Strategy B: Vision fallback (screenshot the page)
        return self._extract_via_vision()

    def _extract_via_api(self) -> dict[str, Any]:
        """Extract lab results using LabCorp's portal REST API."""

        # Step 1: Fetch results headers (list of all results)
        try:
            headers_resp = self.page.request.get(HEADERS_URL)
            if not headers_resp.ok:
                return self._empty_result(
                    f"Headers API returned {headers_resp.status} "
                    f"(URL: {self.page.url})"
                )
            results_list = headers_resp.json()
        except Exception as e:
            return self._empty_result(f"Headers API error: {e} (URL: {self.page.url})")

        if not results_list:
            return self._empty_result("No results returned from API")

        # Step 2: Fetch detail for each result
        results: list[dict[str, Any]] = []
        for header in results_list:
            result_id = header.get("id")
            if not result_id or not header.get("isDetailAvailable"):
                continue

            try:
                detail_url = f"{API_BASE}/current/linkedAccounts/results/{result_id}"
                detail_resp = self.page.request.get(detail_url)
                if not detail_resp.ok:
                    continue

                detail = detail_resp.json()
                result_data = self._parse_api_detail(header, detail)
                if result_data:
                    results.append(result_data)
            except Exception:
                continue

        return {
            "data_type": "lab_results",
            "account_name": "LabCorp",
            "results": results,
        }

    def _parse_api_detail(self, header: dict, detail: dict) -> dict[str, Any] | None:
        """Parse a single result's API detail response into our standard format."""
        # Extract dates — API returns ISO timestamps
        date_of_service = header.get("dateOfService", "")
        result_date = date_of_service[:10] if date_of_service else None
        order_date = (header.get("orderedDate") or "")[:10] or None

        result_data: dict[str, Any] = {
            "patient_name": header.get("patientName", ""),
            "provider": "LabCorp",
            "ordering_physician": header.get("orderingProviderName", ""),
            "order_date": order_date,
            "result_date": result_date,
            "panels": [],
        }

        # Parse ordered items (panels)
        for item in detail.get("orderedItems", []):
            panel_name = item.get("testName", "Unknown")
            api_results = item.get("results", [])

            if not api_results:
                continue

            markers: list[dict[str, Any]] = []
            for r in api_results:
                name = r.get("name", "")
                value = r.get("value", "")

                # Skip comment/note entries (no value, name starts with "Please Note")
                if not value or name.startswith("Please Note"):
                    continue

                # Parse reference range (e.g., "3.4-10.8", ">39", "Not Estab.")
                ref_range = r.get("referenceRange", "") or ""
                ref_low, ref_high = self._parse_reference_range(ref_range)

                # Map abnormal indicator to our flag system
                flag = self._map_abnormal_indicator(r.get("abnormalIndicator"))

                markers.append({
                    "marker_name": name,
                    "value": value,
                    "unit": r.get("units") or "",
                    "reference_low": ref_low,
                    "reference_high": ref_high,
                    "flag": flag,
                })

            if markers:
                result_data["panels"].append({
                    "panel_name": panel_name,
                    "markers": markers,
                })

        return result_data if result_data["panels"] else None

    @staticmethod
    def _parse_reference_range(ref_range: str) -> tuple[str, str]:
        """Parse a reference range string into (low, high) values."""
        if not ref_range or ref_range in ("Not Estab.", "None"):
            return "", ""

        # Standard range: "3.4-10.8"
        match = re.match(r"([\d.<>]+)\s*[-–]\s*([\d.<>]+)", ref_range)
        if match:
            return match.group(1), match.group(2)

        # Lower bound only: ">39", ">=59"
        match = re.match(r"[>≥]=?\s*([\d.]+)", ref_range)
        if match:
            return match.group(1), ""

        # Upper bound only: "<130", "<=5.6"
        match = re.match(r"[<≤]=?\s*([\d.]+)", ref_range)
        if match:
            return "", match.group(1)

        return "", ""

    @staticmethod
    def _map_abnormal_indicator(indicator: str | None) -> str:
        """Map LabCorp API abnormal indicator to our flag values."""
        if not indicator or indicator == "N":
            return "normal"
        if indicator in ("H", "HH"):
            return "high" if indicator == "H" else "critical"
        if indicator in ("L", "LL"):
            return "low" if indicator == "L" else "critical"
        if indicator in ("A", "C"):
            return "critical"
        # None indicator (e.g., for qualitative results like "Negative")
        return "normal"

    def _extract_via_vision(self) -> dict[str, Any]:
        """Fallback: screenshot results page and extract via vision API."""
        try:
            from circuitai.services.capture_service import CaptureService, HAS_ANTHROPIC

            if not HAS_ANTHROPIC:
                return self._empty_result("Vision API unavailable (anthropic not installed)")

            capture_svc = CaptureService(self.browser_service.db)
            if not capture_svc.is_configured():
                return self._empty_result("Vision API unavailable (no API key configured)")

            from pathlib import Path
            import tempfile

            screenshot_path = Path(tempfile.mktemp(suffix=".png"))
            self.page.screenshot(path=str(screenshot_path), full_page=True)

            try:
                import base64
                import json as json_mod

                api_key = capture_svc._get_api_key()
                image_data = base64.b64encode(screenshot_path.read_bytes()).decode("utf-8")

                import anthropic
                client = anthropic.Anthropic(api_key=api_key)
                message = client.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=4096,
                    messages=[{
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/png",
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": (
                                    "Extract lab test results from this LabCorp patient portal screenshot. "
                                    "Return JSON with: {results: [{result_date, panels: [{panel_name, "
                                    "markers: [{marker_name, value, unit, reference_low, reference_high, flag}]}]}]}"
                                ),
                            },
                        ],
                    }],
                )

                raw = message.content[0].text.strip()
                if raw.startswith("```"):
                    raw = re.sub(r"^```(?:json)?\s*", "", raw)
                    raw = re.sub(r"\s*```$", "", raw)

                parsed = json_mod.loads(raw)
                lab_results = parsed.get("results", [])
                for r in lab_results:
                    r.setdefault("provider", "LabCorp")
                    r.setdefault("patient_name", "")
                    r.setdefault("ordering_physician", "")

                return {
                    "data_type": "lab_results",
                    "account_name": "LabCorp",
                    "results": lab_results,
                }
            finally:
                screenshot_path.unlink(missing_ok=True)

        except Exception:
            return self._empty_result("API and vision extraction both failed")

    def _empty_result(self, reason: str = "") -> dict[str, Any]:
        return {
            "data_type": "lab_results",
            "account_name": "LabCorp",
            "results": [],
            "error": reason,
        }

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        match = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", date_str)
        if not match:
            return date_str
        month, day, year = match.groups()
        if len(year) == 2:
            year = f"20{year}"
        return f"{year}-{int(month):02d}-{int(day):02d}"
