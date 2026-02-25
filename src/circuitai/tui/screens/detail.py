"""Detail screens for TUI drill-down navigation."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from circuitai.core.database import DatabaseConnection
from circuitai.output.formatter import dollars, format_date


class DetailScreen(Screen):
    """Base detail screen with back navigation."""

    BINDINGS = [
        Binding("escape", "go_back", "Back"),
        Binding("q", "go_back", "Back"),
    ]

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def action_go_back(self) -> None:
        self.app.pop_screen()


class BillsDetailScreen(DetailScreen):
    """Detailed view of all bills with payment history."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(Static(id="bills-detail-content"))
        yield Footer()

    def on_mount(self) -> None:
        from circuitai.services.bill_service import BillService

        svc = BillService(self.db)
        bills = svc.list_bills()

        lines = ["[bold yellow]All Bills — Detail View[/bold yellow]\n"]
        for b in bills:
            lines.append(f"  [bold]{b.name}[/bold]")
            lines.append(f"    Provider:  {b.provider}")
            lines.append(f"    Amount:    {dollars(b.amount_cents)}")
            lines.append(f"    Due Day:   {b.due_day or '—'}")
            lines.append(f"    Frequency: {b.frequency}")
            lines.append(f"    Auto-pay:  {'Yes' if b.auto_pay else 'No'}")

            last = svc.get_last_payment(b.id)
            if last:
                lines.append(
                    f"    Last Paid: {format_date(last.paid_date)} "
                    f"({dollars(last.amount_cents)})"
                )
            else:
                lines.append("    Last Paid: [dim]Never[/dim]")
            lines.append("")

        if not bills:
            lines.append("  [dim]No bills found.[/dim]")

        self.query_one("#bills-detail-content", Static).update("\n".join(lines))


class AccountsDetailScreen(DetailScreen):
    """Detailed view of accounts with recent transactions."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(Static(id="accounts-detail-content"))
        yield Footer()

    def on_mount(self) -> None:
        from circuitai.services.account_service import AccountService

        svc = AccountService(self.db)
        accounts = svc.list_accounts()

        lines = ["[bold green]Bank Accounts — Detail View[/bold green]\n"]
        for a in accounts:
            last4 = f"****{a.last_four}" if a.last_four else ""
            lines.append(f"  [bold]{a.name}[/bold]  {last4}")
            lines.append(f"    Institution: {a.institution}")
            lines.append(f"    Type:        {a.account_type}")
            lines.append(f"    Balance:     {dollars(a.balance_cents)}")

            txns = svc.get_transactions(a.id, limit=5)
            if txns:
                lines.append("    Recent Transactions:")
                for t in txns:
                    sign = "+" if t.amount_cents > 0 else ""
                    lines.append(
                        f"      {format_date(t.transaction_date)} "
                        f"{t.description}: {sign}{dollars(t.amount_cents)}"
                    )
            lines.append("")

        total = svc.get_total_balance()
        lines.append(f"  [bold]Total Balance: {dollars(total)}[/bold]")

        self.query_one("#accounts-detail-content", Static).update("\n".join(lines))


class CardsDetailScreen(DetailScreen):
    """Detailed view of credit cards."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(Static(id="cards-detail-content"))
        yield Footer()

    def on_mount(self) -> None:
        from circuitai.services.card_service import CardService

        svc = CardService(self.db)
        cards = svc.list_cards()

        lines = ["[bold red]Credit Cards — Detail View[/bold red]\n"]
        for c in cards:
            util = f"{c.utilization:.0f}%" if c.credit_limit_cents else "—"
            lines.append(f"  [bold]{c.name}[/bold]  ****{c.last_four}")
            lines.append(f"    Institution: {c.institution}")
            lines.append(
                f"    Balance:     {dollars(c.balance_cents)} / "
                f"{dollars(c.credit_limit_cents)}"
            )
            lines.append(f"    Utilization: {util}")
            lines.append("")

        total = svc.get_total_balance()
        lines.append(f"  [bold]Total Owed: {dollars(total)}[/bold]")

        self.query_one("#cards-detail-content", Static).update("\n".join(lines))


class DeadlinesDetailScreen(DetailScreen):
    """Detailed view of deadlines."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(Static(id="deadlines-detail-content"))
        yield Footer()

    def on_mount(self) -> None:
        from circuitai.services.deadline_service import DeadlineService

        svc = DeadlineService(self.db)
        overdue = svc.get_overdue()
        upcoming = svc.get_upcoming(within_days=30)

        lines = ["[bold magenta]Deadlines — Detail View[/bold magenta]\n"]

        if overdue:
            lines.append("  [bold red]OVERDUE[/bold red]")
            for d in overdue:
                lines.append(f"    [red]{d.title} — due {d.due_date}[/red]")
                if d.description:
                    lines.append(f"      {d.description}")
            lines.append("")

        if upcoming:
            lines.append("  [bold]Upcoming[/bold]")
            for d in upcoming:
                days = f"in {d.days_until}d" if d.days_until is not None else ""
                prio = f"[{d.priority}]" if d.priority != "medium" else ""
                lines.append(f"    {d.title:<30} {d.due_date}  {days} {prio}")
                if d.description:
                    lines.append(f"      {d.description}")

        if not overdue and not upcoming:
            lines.append("  [dim]No deadlines[/dim]")

        self.query_one("#deadlines-detail-content", Static).update("\n".join(lines))


class InvestmentsDetailScreen(DetailScreen):
    """Detailed view of investments."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(Static(id="investments-detail-content"))
        yield Footer()

    def on_mount(self) -> None:
        from circuitai.services.investment_service import InvestmentService

        svc = InvestmentService(self.db)
        investments = svc.list_investments()

        lines = ["[bold cyan]Investments — Detail View[/bold cyan]\n"]
        for inv in investments:
            gain = f"{inv.gain_loss_pct:+.1f}%"
            lines.append(f"  [bold]{inv.name}[/bold]  ({inv.account_type})")
            lines.append(f"    Institution: {inv.institution}")
            lines.append(f"    Value:       {dollars(inv.current_value_cents)}")
            lines.append(f"    Cost Basis:  {dollars(inv.cost_basis_cents)}")
            lines.append(f"    Gain/Loss:   {gain}")
            lines.append("")

        total = svc.get_total_value()
        lines.append(f"  [bold]Total Value: {dollars(total)}[/bold]")

        self.query_one("#investments-detail-content", Static).update("\n".join(lines))


class ActivitiesDetailScreen(DetailScreen):
    """Detailed view of kids activities."""

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(Static(id="activities-detail-content"))
        yield Footer()

    def on_mount(self) -> None:
        from circuitai.services.activity_service import ActivityService

        svc = ActivityService(self.db)
        activities = svc.list_activities()

        lines = ["[bold blue]Kids Activities — Detail View[/bold blue]\n"]
        for a in activities:
            child_name = "—"
            if a.child_id:
                try:
                    child = svc.get_child(a.child_id)
                    child_name = child.name
                except Exception:
                    pass

            lines.append(f"  [bold]{a.name}[/bold]  ({a.sport_or_type})")
            lines.append(f"    Child:    {child_name}")
            lines.append(f"    Schedule: {a.schedule or '—'}")
            lines.append(f"    Location: {a.location or '—'}")
            lines.append(f"    Cost:     {dollars(a.cost_cents)}")
            lines.append(f"    Season:   {a.season or '—'}")
            lines.append("")

        if not activities:
            lines.append("  [dim]No activities[/dim]")

        self.query_one("#activities-detail-content", Static).update("\n".join(lines))
