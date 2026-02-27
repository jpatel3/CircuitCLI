"""Tests for browser automation — BrowserService, site registry, JCPL adapter, and CLI commands."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database


# ── Fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test_browser.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


@pytest.fixture
def cli_runner(db):
    from circuitai.cli.main import CircuitContext

    runner = CliRunner()

    def patched_get_db(self):
        self._db = db
        return db

    with patch.object(CircuitContext, "get_db", patched_get_db):
        yield runner


# ── Site Registry Tests ─────────────────────────────────────────────


class TestSiteRegistry:
    def test_jcpl_registered(self):
        from circuitai.services.sites import SITE_REGISTRY

        assert "jcpl" in SITE_REGISTRY

    def test_get_site_returns_jcpl(self):
        from circuitai.services.sites import get_site
        from circuitai.services.sites.jcpl import JCPLSite

        cls = get_site("jcpl")
        assert cls is JCPLSite

    def test_get_site_unknown_raises(self):
        from circuitai.services.sites import get_site

        with pytest.raises(KeyError, match="Unknown site"):
            get_site("nonexistent")

    def test_list_sites(self):
        from circuitai.services.sites import list_sites

        sites = list_sites()
        assert len(sites) >= 1
        jcpl = next(s for s in sites if s["key"] == "jcpl")
        assert jcpl["name"] == "Jersey Central Power & Light"
        assert jcpl["domain"] == "firstenergycorp.com"
        assert jcpl["category"] == "electricity"

    def test_register_site_decorator(self):
        from circuitai.services.sites import SITE_REGISTRY, register_site
        from circuitai.services.sites.base import BaseSite

        @register_site("test_site_xyz")
        class TestSite(BaseSite):
            DISPLAY_NAME = "Test"
            DOMAIN = "test.com"

            def login(self, u, p):
                return True

            def handle_2fa(self):
                return True

            def extract_billing(self):
                return {}

        assert "test_site_xyz" in SITE_REGISTRY
        assert SITE_REGISTRY["test_site_xyz"] is TestSite
        # Cleanup
        del SITE_REGISTRY["test_site_xyz"]


# ── Credential Tests ────────────────────────────────────────────────


class TestCredentials:
    @patch("circuitai.services.browser_service.keyring")
    def test_save_and_get_credentials(self, mock_keyring, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        stored = {}

        def set_pw(service, key, value):
            stored[(service, key)] = value

        def get_pw(service, key):
            return stored.get((service, key))

        mock_keyring.set_password.side_effect = set_pw
        mock_keyring.get_password.side_effect = get_pw

        svc.save_credentials("jcpl", "user@test.com", "secret123")

        creds = svc.get_credentials("jcpl")
        assert creds == ("user@test.com", "secret123")

    @patch("circuitai.services.browser_service.keyring")
    def test_has_credentials_true(self, mock_keyring, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        stored = {}

        def set_pw(service, key, value):
            stored[(service, key)] = value

        def get_pw(service, key):
            return stored.get((service, key))

        mock_keyring.set_password.side_effect = set_pw
        mock_keyring.get_password.side_effect = get_pw

        svc.save_credentials("jcpl", "user@test.com", "pass")
        assert svc.has_credentials("jcpl") is True

    @patch("circuitai.services.browser_service.keyring")
    def test_has_credentials_false(self, mock_keyring, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)
        mock_keyring.get_password.return_value = None
        assert svc.has_credentials("jcpl") is False

    @patch("circuitai.services.browser_service.keyring")
    def test_delete_credentials(self, mock_keyring, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        stored = {}

        def set_pw(service, key, value):
            stored[(service, key)] = value

        def get_pw(service, key):
            return stored.get((service, key))

        def del_pw(service, key):
            stored.pop((service, key), None)

        mock_keyring.set_password.side_effect = set_pw
        mock_keyring.get_password.side_effect = get_pw
        mock_keyring.delete_password.side_effect = del_pw

        svc.save_credentials("jcpl", "user@test.com", "pass")
        svc.delete_credentials("jcpl")

        assert svc.get_credentials("jcpl") is None

    @patch("circuitai.services.browser_service.keyring")
    def test_get_credentials_missing_password(self, mock_keyring, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        def get_pw(service, key):
            if key == "_username":
                return "user@test.com"
            return None

        mock_keyring.get_password.side_effect = get_pw

        assert svc.get_credentials("jcpl") is None


# ── Browser Launch Tests ────────────────────────────────────────────


class TestBrowserLaunch:
    def test_launch_requires_playwright(self, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        with patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", False):
            with pytest.raises(Exception, match="playwright.*not installed"):
                svc.launch_browser()

    @patch("circuitai.services.browser_service.sync_playwright", create=True)
    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True)
    def test_launch_browser_visible(self, mock_sync_pw, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        mock_pw = MagicMock()
        mock_sync_pw.return_value.start.return_value = mock_pw
        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        _browser, _context, page = svc.launch_browser()

        call_kwargs = mock_pw.chromium.launch_persistent_context.call_args
        assert call_kwargs.kwargs["headless"] is False
        assert page is mock_page

        svc.close_browser()

    @patch("circuitai.services.browser_service.sync_playwright", create=True)
    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True)
    def test_launch_browser_persistent_context(self, mock_sync_pw, db):
        from circuitai.services.browser_service import BrowserService, BROWSER_DATA_DIR

        svc = BrowserService(db)

        mock_pw = MagicMock()
        mock_sync_pw.return_value.start.return_value = mock_pw
        mock_context = MagicMock()
        mock_context.pages = [MagicMock()]
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        svc.launch_browser()

        call_args = mock_pw.chromium.launch_persistent_context.call_args
        user_data_dir = call_args.kwargs.get("user_data_dir") or (call_args.args[0] if call_args.args else "")
        assert str(BROWSER_DATA_DIR) in user_data_dir

        svc.close_browser()

    @patch("circuitai.services.browser_service.sync_playwright", create=True)
    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True)
    def test_close_browser_cleanup(self, mock_sync_pw, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        mock_pw = MagicMock()
        mock_sync_pw.return_value.start.return_value = mock_pw
        mock_context = MagicMock()
        mock_context.pages = [MagicMock()]
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        svc.launch_browser()
        svc.close_browser()

        mock_context.close.assert_called_once()
        mock_pw.stop.assert_called_once()


# ── JCPL Login Tests ────────────────────────────────────────────────


class TestJCPLLogin:
    def _make_site(self):
        from circuitai.services.sites.jcpl import JCPLSite

        page = MagicMock()
        browser_svc = MagicMock()
        site = JCPLSite(page, browser_svc)
        return site, page

    def _setup_login_mocks(self, page):
        """Set up page mocks that pass login but not 2FA detection."""
        # 2FA selectors contain "verification", "security code", "two-factor", "2-step", "otpCode", etc.
        # Form selectors contain "loginUsernameInput", "username", "password", "submit", etc.
        twofa_keywords = {"verification", "security code", "two-factor", "2-step", "otpCode", "verificationCode", "otpInput"}
        mock_input = MagicMock()
        mock_input.is_visible.return_value = True

        def selective_query(sel):
            # Return None for 2FA indicator selectors
            for kw in twofa_keywords:
                if kw in sel:
                    return None
            return mock_input

        page.query_selector.side_effect = selective_query
        page.url = "https://www.firstenergycorp.com/account/dashboard"
        return mock_input

    def test_login_navigates_to_correct_url(self):
        from circuitai.services.sites.jcpl import LOGIN_URL

        site, page = self._make_site()
        self._setup_login_mocks(page)

        site.login("user@test.com", "password123")

        page.goto.assert_called()
        first_goto = page.goto.call_args_list[0]
        assert LOGIN_URL in first_goto.args[0]

    def test_login_fills_username_and_password(self):
        site, page = self._make_site()
        mock_input = self._setup_login_mocks(page)

        site.login("user@test.com", "secret")

        fill_calls = [c for c in mock_input.fill.call_args_list]
        assert len(fill_calls) >= 2
        assert fill_calls[0].args[0] == "user@test.com"
        assert fill_calls[1].args[0] == "secret"

    def test_login_clicks_submit(self):
        site, page = self._make_site()
        mock_input = self._setup_login_mocks(page)

        site.login("user@test.com", "pass")

        mock_input.click.assert_called()

    def test_login_fails_no_username_field(self):
        site, page = self._make_site()

        page.query_selector.return_value = None

        result = site.login("user@test.com", "pass")
        assert result is False

    def test_login_detects_success_via_url(self):
        site, page = self._make_site()
        self._setup_login_mocks(page)

        result = site.login("user@test.com", "pass")
        assert result is True


# ── JCPL 2FA Tests ──────────────────────────────────────────────────


class TestJCPL2FA:
    def _make_site(self):
        from circuitai.services.sites.jcpl import JCPLSite

        page = MagicMock()
        browser_svc = MagicMock()
        return JCPLSite(page, browser_svc), page

    def test_needs_2fa_detects_verification_page(self):
        site, page = self._make_site()

        mock_el = MagicMock()

        def query_side_effect(sel):
            if "verification" in sel or "otpCode" in sel:
                return mock_el
            return None

        page.query_selector.side_effect = query_side_effect

        assert site.needs_2fa() is True

    def test_needs_2fa_false_when_no_indicator(self):
        site, page = self._make_site()
        page.query_selector.return_value = None

        assert site.needs_2fa() is False

    @patch("circuitai.services.sites.jcpl.click")
    def test_handle_2fa_prompts_user(self, mock_click):
        site, page = self._make_site()

        mock_click.prompt.return_value = "123456"

        mock_input = MagicMock()
        mock_input.is_visible.return_value = True
        page.query_selector.return_value = mock_input
        page.url = "https://www.firstenergycorp.com/account"

        site.handle_2fa()

        mock_click.prompt.assert_called_once()
        mock_input.fill.assert_any_call("123456")

    @patch("circuitai.services.sites.jcpl.click")
    def test_handle_2fa_empty_code_fails(self, mock_click):
        site, page = self._make_site()
        mock_click.prompt.return_value = ""

        result = site.handle_2fa()
        assert result is False


# ── JCPL Extract Tests ──────────────────────────────────────────────


class TestJCPLExtract:
    def _make_site(self):
        from circuitai.services.sites.jcpl import JCPLSite

        page = MagicMock()
        browser_svc = MagicMock()
        return JCPLSite(page, browser_svc), page

    def test_extract_dom_parses_balance(self):
        site, page = self._make_site()

        def query_selector_side(sel):
            if sel in (".amount-due", ".balance-due"):
                el = MagicMock()
                el.inner_text.return_value = "$142.57"
                return el
            return None

        page.query_selector.side_effect = query_selector_side
        page.query_selector_all.return_value = []
        page.inner_text.return_value = ""

        result = site._extract_from_dom()
        assert result["current_balance_cents"] == 14257

    def test_extract_dom_parses_bill_rows(self):
        site, page = self._make_site()

        page.query_selector.return_value = None

        row1 = MagicMock()
        row1.inner_text.return_value = "01/15/2025  JCPL Electric  $142.57"
        row2 = MagicMock()
        row2.inner_text.return_value = "12/15/2024  JCPL Electric  $138.20"
        page.query_selector_all.return_value = [row1, row2]

        page.inner_text.return_value = "Amount Due: $142.57"

        result = site._extract_from_dom()
        assert len(result["bills"]) == 2
        assert result["bills"][0]["amount_cents"] == 14257
        assert result["bills"][0]["date"] == "2025-01-15"
        assert result["bills"][1]["amount_cents"] == 13820
        assert result["bills"][1]["date"] == "2024-12-15"

    def test_extract_dom_balance_from_body_text(self):
        site, page = self._make_site()

        page.query_selector.return_value = None
        page.query_selector_all.return_value = []
        # Use a pattern that matches the regex: "Amount Due: $256.78"
        page.inner_text.return_value = "Your Balance Due: $256.78"

        result = site._extract_from_dom()
        assert result["current_balance_cents"] == 25678

    def test_extract_dom_empty_page(self):
        site, page = self._make_site()

        page.query_selector.return_value = None
        page.query_selector_all.return_value = []
        page.inner_text.return_value = "Welcome to FirstEnergy"

        result = site._extract_from_dom()
        assert result["current_balance_cents"] is None
        assert result["bills"] == []

    def test_parse_dollar_amount(self):
        from circuitai.services.sites.jcpl import JCPLSite

        assert JCPLSite._parse_dollar_amount("$142.57") == 14257
        assert JCPLSite._parse_dollar_amount("1,234.56") == 123456
        assert JCPLSite._parse_dollar_amount("$0.99") == 99
        assert JCPLSite._parse_dollar_amount("") is None
        assert JCPLSite._parse_dollar_amount("abc") is None

    def test_normalize_date(self):
        from circuitai.services.sites.jcpl import JCPLSite

        assert JCPLSite._normalize_date("01/15/2025") == "2025-01-15"
        assert JCPLSite._normalize_date("12-05-24") == "2024-12-05"
        assert JCPLSite._normalize_date("1/5/2025") == "2025-01-05"

    def test_extract_via_vision_fallback(self):
        site, page = self._make_site()
        site.browser_service.db = MagicMock()

        page.query_selector.return_value = None
        page.query_selector_all.return_value = []
        page.inner_text.return_value = ""

        mock_capture_svc = MagicMock()
        mock_capture_svc.is_configured.return_value = True
        mock_capture_svc.extract_from_screenshot.return_value = {
            "account_name": "JCPL Account",
            "balance_cents": -15000,
            "transactions": [
                {"date": "2025-01-15", "amount_cents": -15000, "description": "JCPL Bill"},
            ],
        }

        # Patch at the source module since _extract_via_vision does:
        # from circuitai.services.capture_service import CaptureService, HAS_ANTHROPIC
        with patch("circuitai.services.capture_service.HAS_ANTHROPIC", True):
            with patch("circuitai.services.capture_service.CaptureService", return_value=mock_capture_svc):
                result = site._extract_via_vision()

        assert result["current_balance_cents"] == 15000
        assert len(result["bills"]) == 1
        assert result["bills"][0]["amount_cents"] == 15000


# ── Import + Dedup Tests ────────────────────────────────────────────


class TestImportBillData:
    def test_import_creates_bill(self, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        data = {
            "account_name": "JCPL Electric",
            "current_balance_cents": 14257,
            "category": "electricity",
            "bills": [
                {"date": "2025-01-15", "amount_cents": 14257, "description": "JCPL Electric Bill"},
            ],
        }

        result = svc.import_bill_data("jcpl", data)

        assert result["bill_name"] == "JCPL Electric"
        assert result["amount_cents"] == 14257
        assert result["imported"] == 1
        assert result["skipped"] == 0

    def test_import_dedup_skips_duplicate(self, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        data = {
            "account_name": "JCPL Electric",
            "current_balance_cents": 14257,
            "category": "electricity",
            "bills": [
                {"date": "2025-01-15", "amount_cents": 14257, "description": "JCPL Electric Bill"},
            ],
        }

        result1 = svc.import_bill_data("jcpl", data)
        assert result1["imported"] == 1

        result2 = svc.import_bill_data("jcpl", data)
        assert result2["imported"] == 0
        assert result2["skipped"] == 1

    def test_import_empty_bills(self, db):
        from circuitai.services.browser_service import BrowserService

        svc = BrowserService(db)

        data = {
            "account_name": "JCPL",
            "current_balance_cents": 10000,
            "category": "electricity",
            "bills": [],
        }

        result = svc.import_bill_data("jcpl", data)
        assert result["imported"] == 0
        assert result["skipped"] == 0

    def test_import_reuses_existing_bill(self, db):
        from circuitai.services.bill_service import BillService
        from circuitai.services.browser_service import BrowserService

        bill_svc = BillService(db)
        bill = bill_svc.add_bill(name="JCPL Electric", provider="JCPL", category="electricity", amount_cents=10000)

        svc = BrowserService(db)
        data = {
            "account_name": "JCPL Electric",
            "current_balance_cents": 14257,
            "category": "electricity",
            "bills": [
                {"date": "2025-02-15", "amount_cents": 14257, "description": "JCPL Bill"},
            ],
        }

        result = svc.import_bill_data("jcpl", data)

        assert result["bill_name"] == "JCPL Electric"
        assert result["imported"] == 1

        updated = bill_svc.get_bill(bill.id)
        assert updated.amount_cents == 14257


# ── CLI Command Tests ───────────────────────────────────────────────


class TestBrowseCLI:
    def test_list_sites(self, cli_runner):
        from circuitai.cli.main import cli

        result = cli_runner.invoke(cli, ["browse", "list-sites"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Jersey Central Power" in result.output

    def test_list_sites_json(self, cli_runner):
        from circuitai.cli.main import cli

        result = cli_runner.invoke(cli, ["--json", "browse", "list-sites"], catch_exceptions=False)
        assert result.exit_code == 0
        envelope = json.loads(result.output)
        assert envelope["status"] == "success"
        sites = envelope["data"]
        assert isinstance(sites, list)
        assert any(s["key"] == "jcpl" for s in sites)

    @patch("circuitai.services.browser_service.keyring")
    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True)
    def test_status_shows_sites(self, mock_keyring, cli_runner):
        from circuitai.cli.main import cli

        mock_keyring.get_password.return_value = None

        result = cli_runner.invoke(cli, ["browse", "status"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Jersey Central" in result.output or "JCPL" in result.output or "jcpl" in result.output

    @patch("circuitai.services.browser_service.keyring")
    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True)
    def test_setup_saves_credentials(self, mock_keyring, cli_runner):
        from circuitai.cli.main import cli

        stored = {}
        mock_keyring.set_password.side_effect = lambda s, k, v: stored.update({(s, k): v})

        result = cli_runner.invoke(
            cli,
            ["browse", "setup", "jcpl"],
            input="user@test.com\nsecret123\n",
            catch_exceptions=False,
        )
        assert result.exit_code == 0
        assert "saved" in result.output.lower() or "Credentials" in result.output

    def test_setup_unknown_site(self, cli_runner):
        from circuitai.cli.main import cli

        with patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True):
            result = cli_runner.invoke(
                cli,
                ["browse", "setup", "nonexistent"],
                catch_exceptions=False,
            )
            assert result.exit_code == 0
            assert "Unknown site" in result.output or "unknown" in result.output.lower()

    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", False)
    def test_setup_no_playwright(self, cli_runner):
        from circuitai.cli.main import cli

        result = cli_runner.invoke(cli, ["browse", "setup", "jcpl"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "playwright" in result.output.lower()

    @patch("circuitai.services.browser_service.keyring")
    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True)
    def test_sync_no_credentials(self, mock_keyring, cli_runner):
        from circuitai.cli.main import cli

        mock_keyring.get_password.return_value = None

        result = cli_runner.invoke(cli, ["browse", "sync", "jcpl"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "No credentials" in result.output or "credentials" in result.output.lower()

    @patch("circuitai.services.browser_service.sync_playwright", create=True)
    @patch("circuitai.services.browser_service.keyring")
    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", True)
    def test_sync_full_flow(self, mock_keyring, mock_sync_pw, cli_runner, db):
        from circuitai.cli.main import cli

        stored = {
            ("circuitai:jcpl", "_username"): "user@test.com",
            ("circuitai:jcpl", "user@test.com"): "pass123",
        }
        mock_keyring.get_password.side_effect = lambda s, k: stored.get((s, k))

        mock_pw = MagicMock()
        mock_sync_pw.return_value.start.return_value = mock_pw

        mock_page = MagicMock()
        mock_context = MagicMock()
        mock_context.pages = [mock_page]
        mock_pw.chromium.launch_persistent_context.return_value = mock_context

        mock_page.url = "https://www.firstenergycorp.com/account/dashboard"

        mock_input = MagicMock()
        mock_input.is_visible.return_value = True
        mock_page.query_selector.return_value = mock_input

        mock_page.query_selector_all.return_value = []
        mock_page.inner_text.return_value = "Amount Due: $142.57"

        result = cli_runner.invoke(cli, ["browse", "sync", "jcpl"], catch_exceptions=False)
        assert result.exit_code == 0

    def test_status_json_no_playwright(self, cli_runner):
        from circuitai.cli.main import cli

        with patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", False):
            result = cli_runner.invoke(cli, ["--json", "browse", "status"], catch_exceptions=False)
            assert result.exit_code == 0
            envelope = json.loads(result.output)
            assert envelope["status"] == "success"
            assert envelope["data"]["playwright_installed"] is False


# ── Feature Flag Tests ──────────────────────────────────────────────


class TestFeatureFlag:
    def test_has_playwright_flag_exists(self):
        from circuitai.services.browser_service import HAS_PLAYWRIGHT

        assert isinstance(HAS_PLAYWRIGHT, bool)

    @patch("circuitai.services.browser_service.HAS_PLAYWRIGHT", False)
    def test_sync_without_playwright_shows_install_message(self, cli_runner):
        from circuitai.cli.main import cli

        result = cli_runner.invoke(cli, ["browse", "sync", "jcpl"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "pip install" in result.output or "playwright" in result.output.lower()
