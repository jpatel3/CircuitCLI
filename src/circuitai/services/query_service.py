"""Natural language query service — regex-based question answering."""

from __future__ import annotations

import re
from typing import Any

from circuitai.core.database import DatabaseConnection
from circuitai.output.formatter import dollars, format_date


class QueryService:
    """Answers natural language questions about the user's financial data."""

    def __init__(self, db: DatabaseConnection) -> None:
        self.db = db

    def query(self, text: str) -> str:
        """Route a question to the appropriate handler and return a human-readable answer."""
        text_lower = text.lower().strip().rstrip("?")

        # Bill queries
        if re.search(r"\bbills?\b.*\bdue\b|\bdue\b.*\bbills?\b", text_lower):
            return self._bills_due(text_lower)

        if re.search(r"\b(electric|water|gas|internet|cable|hoa|tax|insurance|phone)\b", text_lower):
            return self._specific_bill(text_lower)

        if re.search(r"\bbills?\b", text_lower):
            return self._bills_overview()

        # Account queries
        if re.search(r"\bbalance|checking|savings|account\b", text_lower):
            return self._account_info(text_lower)

        # Card queries
        if re.search(r"\bcredit\s*card|amex|citi|visa|mastercard\b", text_lower):
            return self._card_info(text_lower)

        # Investment queries
        if re.search(r"\binvestment|401k|529|ira|portfolio|stock\b", text_lower):
            return self._investment_info(text_lower)

        # Mortgage queries
        if re.search(r"\bmortgage|home\s*loan\b", text_lower):
            return self._mortgage_info()

        # Activity queries
        if re.search(r"\bactivit|hockey|soccer|gymnastics|tennis|practice|game|lesson\b", text_lower):
            return self._activity_info(text_lower)

        # Deadline queries
        if re.search(r"\bdeadline|due\s*date|upcoming\b", text_lower):
            return self._deadline_info()

        # Cost/spending queries
        if re.search(r"\bspend|cost|how\s*much|total\b", text_lower):
            return self._spending_info(text_lower)

        # Net worth
        if re.search(r"\bnet\s*worth|financial|summary|overview\b", text_lower):
            return self._summary_info()

        return f"I'm not sure how to answer that. Try asking about bills, accounts, cards, investments, or activities."

    def query_json(self, text: str) -> dict[str, Any]:
        """Return structured query results."""
        return {"query": text, "answer": self.query(text)}

    def _bills_due(self, text: str) -> str:
        from circuitai.services.bill_service import BillService
        svc = BillService(self.db)

        if "this week" in text or "next 7" in text:
            bills = svc.get_due_soon(within_days=7)
        elif "this month" in text:
            bills = svc.get_due_soon(within_days=30)
        else:
            bills = svc.get_due_soon(within_days=7)

        if not bills:
            return "No bills due soon."

        lines = ["Bills due soon:"]
        for b in bills:
            lines.append(f"  • {b.name} — {dollars(b.amount_cents)} (due day {b.due_day})")
        total = sum(b.amount_cents for b in bills)
        lines.append(f"\nTotal: {dollars(total)}")
        return "\n".join(lines)

    def _specific_bill(self, text: str) -> str:
        from circuitai.services.bill_service import BillService
        svc = BillService(self.db)

        # Try to find a matching bill
        keywords = ["electric", "water", "gas", "internet", "cable", "hoa", "tax", "insurance", "phone"]
        for kw in keywords:
            if kw in text:
                bills = svc.search_bills(kw)
                if bills:
                    b = bills[0]
                    last = svc.get_last_payment(b.id)
                    lines = [f"{b.name}: {dollars(b.amount_cents)}/{b.frequency}, due on the {b.due_day}th"]
                    if last:
                        lines.append(f"Last paid: {format_date(last.paid_date)} ({dollars(last.amount_cents)})")
                    return "\n".join(lines)

        return "No matching bill found."

    def _bills_overview(self) -> str:
        from circuitai.services.bill_service import BillService
        svc = BillService(self.db)
        summary = svc.get_summary()

        lines = [
            f"Bills Overview:",
            f"  Total bills: {summary['total_bills']}",
            f"  Monthly total: {dollars(summary['monthly_total_cents'])}",
            f"  Estimated monthly (incl. yearly/quarterly): {dollars(summary['estimated_monthly_cents'])}",
            f"  Due this week: {summary['due_soon']}",
        ]
        return "\n".join(lines)

    def _account_info(self, text: str) -> str:
        from circuitai.services.account_service import AccountService
        svc = AccountService(self.db)
        accounts = svc.list_accounts()

        if not accounts:
            return "No bank accounts set up. Use /accounts add to add one."

        lines = ["Bank Accounts:"]
        for a in accounts:
            last4 = f" ****{a.last_four}" if a.last_four else ""
            lines.append(f"  {a.name}{last4}: {dollars(a.balance_cents)}")
        lines.append(f"\nTotal: {dollars(svc.get_total_balance())}")
        return "\n".join(lines)

    def _card_info(self, text: str) -> str:
        from circuitai.services.card_service import CardService
        svc = CardService(self.db)
        cards = svc.list_cards()

        if not cards:
            return "No credit cards set up. Use /cards add to add one."

        lines = ["Credit Cards:"]
        for c in cards:
            lines.append(f"  {c.name}: {dollars(c.balance_cents)} / {dollars(c.credit_limit_cents)}")
        return "\n".join(lines)

    def _investment_info(self, text: str) -> str:
        from circuitai.services.investment_service import InvestmentService
        svc = InvestmentService(self.db)
        perf = svc.get_performance()

        if perf["count"] == 0:
            return "No investment accounts set up."

        lines = [
            f"Investments:",
            f"  Total value: {dollars(perf['total_value_cents'])}",
            f"  Cost basis: {dollars(perf['total_cost_basis_cents'])}",
            f"  Gain/Loss: {dollars(perf['total_gain_loss_cents'])} ({perf['gain_loss_pct']}%)",
            f"  Accounts: {perf['count']}",
        ]
        return "\n".join(lines)

    def _mortgage_info(self) -> str:
        from circuitai.services.mortgage_service import MortgageService
        svc = MortgageService(self.db)
        mortgages = svc.list_mortgages()

        if not mortgages:
            return "No mortgages set up."

        lines = ["Mortgages:"]
        for m in mortgages:
            lines.append(
                f"  {m.name} ({m.lender}): {dollars(m.balance_cents)} remaining, "
                f"{dollars(m.monthly_payment_cents)}/mo at {m.interest_rate_pct}%"
            )
        return "\n".join(lines)

    def _activity_info(self, text: str) -> str:
        from circuitai.services.activity_service import ActivityService
        svc = ActivityService(self.db)
        activities = svc.list_activities()

        if not activities:
            return "No activities set up."

        lines = ["Activities:"]
        for a in activities:
            child_str = ""
            if a.child_id:
                try:
                    child = svc.get_child(a.child_id)
                    child_str = f" ({child.name})"
                except Exception:
                    pass
            schedule = f" — {a.schedule}" if a.schedule else ""
            location = f" at {a.location}" if a.location else ""
            lines.append(f"  {a.name}{child_str}{schedule}{location}")
        return "\n".join(lines)

    def _deadline_info(self) -> str:
        from circuitai.services.deadline_service import DeadlineService
        svc = DeadlineService(self.db)

        overdue = svc.get_overdue()
        upcoming = svc.get_upcoming(within_days=14)

        lines = []
        if overdue:
            lines.append("OVERDUE:")
            for dl in overdue:
                lines.append(f"  [!] {dl.title} — was due {format_date(dl.due_date)}")

        if upcoming:
            lines.append("Upcoming (14 days):")
            for dl in upcoming:
                lines.append(f"  • {dl.title} — due {format_date(dl.due_date)} ({dl.days_until}d)")

        if not lines:
            return "No deadlines to worry about."
        return "\n".join(lines)

    def _spending_info(self, text: str) -> str:
        from circuitai.services.bill_service import BillService
        svc = BillService(self.db)
        summary = svc.get_summary()
        return (
            f"Monthly spending estimate:\n"
            f"  Bills: {dollars(summary['estimated_monthly_cents'])}/month\n"
            f"  ({summary['total_bills']} active bills)"
        )

    def _summary_info(self) -> str:
        from circuitai.services.summary_service import SummaryService
        svc = SummaryService(self.db)
        s = svc.get_full_summary()

        return (
            f"Financial Summary:\n"
            f"  Net worth: {dollars(s['net_worth_cents'])}\n"
            f"  Bank accounts: {dollars(s['accounts']['total_balance_cents'])}\n"
            f"  Credit cards: -{dollars(s['cards']['total_balance_cents'])}\n"
            f"  Investments: {dollars(s['investments']['total_value_cents'])}\n"
            f"  Mortgage: -{dollars(s['mortgage_balance_cents'])}\n"
            f"  Monthly bills: ~{dollars(s['bills']['estimated_monthly_cents'])}"
        )
