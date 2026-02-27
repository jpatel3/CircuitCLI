"""JCPL (Jersey Central Power & Light) site adapter — FirstEnergy login + billing extraction."""

from __future__ import annotations

import re
from typing import Any

import click

from circuitai.services.sites import register_site
from circuitai.services.sites.base import BaseSite

LOGIN_URL = "https://www.firstenergycorp.com/content/customer/login.html"
BILLING_URL = "https://www.firstenergycorp.com/content/customer/account/billing-payment.html"

# Timeout for page loads and element waits (ms)
NAV_TIMEOUT = 30_000
ELEMENT_TIMEOUT = 15_000


@register_site("jcpl")
class JCPLSite(BaseSite):
    """Browser automation for Jersey Central Power & Light (FirstEnergy)."""

    DISPLAY_NAME = "Jersey Central Power & Light"
    DOMAIN = "firstenergycorp.com"
    BILL_CATEGORY = "electricity"

    def login(self, username: str, password: str) -> bool:
        """Navigate to FirstEnergy login, fill credentials, and submit."""
        self.page.goto(LOGIN_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")

        # Wait for JS-rendered login form
        try:
            self.page.wait_for_selector("#loginUsernameInput, input[name='username'], #user_id",
                                        timeout=ELEMENT_TIMEOUT)
        except Exception:
            # Try broader selector for dynamically loaded forms
            self.page.wait_for_selector("input[type='text'], input[type='email']",
                                        timeout=ELEMENT_TIMEOUT)

        # Fill username — try multiple selectors for FirstEnergy's JS form
        username_selectors = [
            "#loginUsernameInput",
            "input[name='username']",
            "#user_id",
            "input[type='text']",
            "input[type='email']",
        ]
        username_filled = False
        for sel in username_selectors:
            el = self.page.query_selector(sel)
            if el and el.is_visible():
                el.fill(username)
                username_filled = True
                break

        if not username_filled:
            return False

        # Fill password
        password_selectors = [
            "#loginPasswordInput",
            "input[name='password']",
            "#password",
            "input[type='password']",
        ]
        password_filled = False
        for sel in password_selectors:
            el = self.page.query_selector(sel)
            if el and el.is_visible():
                el.fill(password)
                password_filled = True
                break

        if not password_filled:
            return False

        # Click sign-in button
        submit_selectors = [
            "button[type='submit']",
            "#loginButton",
            "input[type='submit']",
            "button:has-text('Sign In')",
            "button:has-text('Log In')",
        ]
        for sel in submit_selectors:
            el = self.page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                break

        # Wait for navigation after login
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT)
        except Exception:
            pass

        # Check for 2FA
        if self.needs_2fa():
            return self.handle_2fa()

        # Verify login succeeded — look for account/dashboard indicators
        return self._verify_logged_in()

    def needs_2fa(self) -> bool:
        """Check if the current page shows a 2FA/MFA prompt."""
        twofa_indicators = [
            "text=verification code",
            "text=security code",
            "text=two-factor",
            "text=2-step",
            "input[name='otpCode']",
            "input[name='verificationCode']",
            "#otpInput",
        ]
        for sel in twofa_indicators:
            try:
                el = self.page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        return False

    def handle_2fa(self) -> bool:
        """Prompt user for 2FA code and enter it on the page."""
        code = click.prompt("\n  Enter 2FA verification code from your phone/email")
        if not code:
            return False

        # Find the 2FA input field
        code_selectors = [
            "input[name='otpCode']",
            "input[name='verificationCode']",
            "#otpInput",
            "input[type='tel']",
            "input[inputmode='numeric']",
        ]
        code_entered = False
        for sel in code_selectors:
            el = self.page.query_selector(sel)
            if el and el.is_visible():
                el.fill(code.strip())
                code_entered = True
                break

        if not code_entered:
            return False

        # Submit the 2FA form
        submit_selectors = [
            "button[type='submit']",
            "button:has-text('Verify')",
            "button:has-text('Submit')",
            "button:has-text('Continue')",
        ]
        for sel in submit_selectors:
            el = self.page.query_selector(sel)
            if el and el.is_visible():
                el.click()
                break

        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=NAV_TIMEOUT)
        except Exception:
            pass

        return self._verify_logged_in()

    def _verify_logged_in(self) -> bool:
        """Check if we're on an authenticated page (account dashboard, billing, etc.)."""
        # Look for common post-login elements
        logged_in_indicators = [
            "text=Account Summary",
            "text=My Account",
            "text=Sign Out",
            "text=Log Out",
            "a[href*='logout']",
            "a[href*='signout']",
        ]
        for sel in logged_in_indicators:
            try:
                el = self.page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue

        # Check URL — if we navigated away from login page, likely succeeded
        current_url = self.page.url.lower()
        if "login" not in current_url and "signin" not in current_url:
            return True

        return False

    def extract_billing(self) -> dict[str, Any]:
        """Navigate to billing page and extract billing data.

        Strategy A: DOM parsing with CSS selectors
        Strategy B: Vision API fallback if DOM parsing fails
        """
        # Navigate to billing page
        self.page.goto(BILLING_URL, timeout=NAV_TIMEOUT, wait_until="domcontentloaded")

        try:
            self.page.wait_for_load_state("networkidle", timeout=ELEMENT_TIMEOUT)
        except Exception:
            pass

        # Strategy A: DOM parsing
        result = self._extract_from_dom()
        if result and (result.get("current_balance_cents") is not None or result.get("bills")):
            return result

        # Strategy B: Vision API fallback
        return self._extract_via_vision()

    def _extract_from_dom(self) -> dict[str, Any]:
        """Try to extract billing data from the DOM."""
        account_name = "JCPL"
        current_balance_cents = None
        bills: list[dict[str, Any]] = []

        # Try to find account name/number
        for sel in [".account-number", ".account-name", "[data-account-number]"]:
            el = self.page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                if text:
                    account_name = f"JCPL {text}"
                    break

        # Try to find current balance
        balance_selectors = [
            ".amount-due",
            ".balance-due",
            ".total-amount-due",
            "[data-amount-due]",
            ".current-balance",
        ]
        for sel in balance_selectors:
            el = self.page.query_selector(sel)
            if el:
                text = el.inner_text().strip()
                cents = self._parse_dollar_amount(text)
                if cents is not None:
                    current_balance_cents = cents
                    break

        # If no targeted selector worked, try a broader text search
        if current_balance_cents is None:
            body_text = self.page.inner_text("body")
            # Look for patterns like "Amount Due: $123.45" or "Total Due $123.45"
            match = re.search(r"(?:amount|total|balance)\s*(?:due)?[:\s]*\$?([\d,]+\.?\d*)", body_text, re.IGNORECASE)
            if match:
                current_balance_cents = self._parse_dollar_amount(match.group(1))

        # Try to find bill history table
        rows = self.page.query_selector_all("table tr, .bill-history-row, .payment-row")
        for row in rows:
            text = row.inner_text()
            # Look for rows with date and dollar amount patterns
            date_match = re.search(r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})", text)
            amount_match = re.search(r"\$?([\d,]+\.\d{2})", text)
            if date_match and amount_match:
                bill_date = self._normalize_date(date_match.group(1))
                amount_cents = self._parse_dollar_amount(amount_match.group(1))
                if bill_date and amount_cents is not None:
                    bills.append({
                        "date": bill_date,
                        "amount_cents": amount_cents,
                        "description": f"JCPL Electric Bill",
                    })

        return {
            "account_name": account_name,
            "current_balance_cents": current_balance_cents,
            "bills": bills,
            "category": self.BILL_CATEGORY,
        }

    def _extract_via_vision(self) -> dict[str, Any]:
        """Fallback: screenshot the billing page and extract via Claude vision API."""
        try:
            from circuitai.services.capture_service import CaptureService, HAS_ANTHROPIC

            if not HAS_ANTHROPIC:
                return self._empty_result("Vision API unavailable (anthropic not installed)")

            capture_svc = CaptureService(self.browser_service.db)
            if not capture_svc.is_configured():
                return self._empty_result("Vision API unavailable (no API key configured)")

            # Take a screenshot of the current page
            from pathlib import Path
            import tempfile

            screenshot_path = Path(tempfile.mktemp(suffix=".png"))
            self.page.screenshot(path=str(screenshot_path), full_page=True)

            try:
                extracted = capture_svc.extract_from_screenshot(screenshot_path)
                # Convert vision API format to our billing format
                balance = extracted.get("balance_cents")
                txns = extracted.get("transactions", [])
                bills = [
                    {
                        "date": t.get("date", ""),
                        "amount_cents": abs(t.get("amount_cents", 0)),
                        "description": t.get("description", "JCPL Electric Bill"),
                    }
                    for t in txns
                    if t.get("date") and t.get("amount_cents")
                ]
                return {
                    "account_name": extracted.get("account_name") or "JCPL",
                    "current_balance_cents": abs(balance) if balance else None,
                    "bills": bills,
                    "category": self.BILL_CATEGORY,
                }
            finally:
                screenshot_path.unlink(missing_ok=True)

        except Exception:
            return self._empty_result("Both DOM and vision extraction failed")

    def _empty_result(self, reason: str = "") -> dict[str, Any]:
        """Return an empty result when extraction fails."""
        return {
            "account_name": "JCPL",
            "current_balance_cents": None,
            "bills": [],
            "category": self.BILL_CATEGORY,
            "error": reason,
        }

    @staticmethod
    def _parse_dollar_amount(text: str) -> int | None:
        """Parse a dollar amount string into cents."""
        if not text:
            return None
        cleaned = re.sub(r"[^\d.]", "", text)
        try:
            return int(round(float(cleaned) * 100))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _normalize_date(date_str: str) -> str:
        """Normalize a date string to YYYY-MM-DD."""
        # Handle MM/DD/YYYY or MM-DD-YYYY
        match = re.match(r"(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})", date_str)
        if not match:
            return date_str
        month, day, year = match.groups()
        if len(year) == 2:
            year = f"20{year}"
        return f"{year}-{int(month):02d}-{int(day):02d}"
