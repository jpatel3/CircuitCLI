"""Abstract base class for browser-automated site adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from playwright.sync_api import Page

    from circuitai.services.browser_service import BrowserService


class BaseSite(ABC):
    """Base class for all site adapters.

    Subclasses implement login, optional 2FA handling, and billing data extraction
    for a specific financial/utility website.
    """

    DISPLAY_NAME: str = ""
    DOMAIN: str = ""
    BILL_CATEGORY: str = "other"

    def __init__(self, page: Page, browser_service: BrowserService) -> None:
        self.page = page
        self.browser_service = browser_service

    @abstractmethod
    def login(self, username: str, password: str) -> bool:
        """Navigate to login page, fill credentials, submit.

        Returns True if login succeeded.
        """

    @abstractmethod
    def handle_2fa(self) -> bool:
        """Prompt user for 2FA code and enter it on the page.

        Returns True if 2FA succeeded.
        """

    @abstractmethod
    def extract_billing(self) -> dict[str, Any]:
        """Navigate to billing page and extract data.

        Returns:
            {
                "account_name": str,
                "current_balance_cents": int,
                "bills": [{"date": str, "amount_cents": int, "description": str}],
            }
        """

    def needs_2fa(self) -> bool:
        """Check if the current page shows a 2FA prompt."""
        return False
