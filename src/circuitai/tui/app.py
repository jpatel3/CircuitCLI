"""Textual TUI dashboard application."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import Footer, Header, Static

from circuitai.core.database import DatabaseConnection
from circuitai.output.formatter import dollars


class SummaryPanel(Static):
    """Financial summary panel."""

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from circuitai.services.summary_service import SummaryService
            svc = SummaryService(self.db)
            s = svc.get_full_summary()
            content = (
                f"[bold cyan]Financial Summary[/bold cyan]\n\n"
                f"  Net Worth:    {dollars(s['net_worth_cents'])}\n"
                f"  Bank:         {dollars(s['accounts']['total_balance_cents'])}\n"
                f"  Credit Cards: -{dollars(s['cards']['total_balance_cents'])}\n"
                f"  Investments:  {dollars(s['investments']['total_value_cents'])}\n"
                f"  Mortgage:     -{dollars(s['mortgage_balance_cents'])}\n"
                f"  Monthly Bills: ~{dollars(s['bills']['estimated_monthly_cents'])}"
            )
            self.update(content)
        except Exception as e:
            self.update(f"[red]Error loading summary: {e}[/red]")


class BillsPanel(Static):
    """Upcoming bills panel."""

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from circuitai.services.bill_service import BillService
            svc = BillService(self.db)
            bills = svc.get_due_soon(within_days=14)

            lines = ["[bold yellow]Upcoming Bills[/bold yellow]\n"]
            if bills:
                for b in bills[:8]:
                    lines.append(f"  {b.name:<20} {dollars(b.amount_cents):>10}  day {b.due_day}")
            else:
                lines.append("  [dim]No bills due soon[/dim]")
            self.update("\n".join(lines))
        except Exception as e:
            self.update(f"[red]Error: {e}[/red]")


class AccountsPanel(Static):
    """Bank accounts panel."""

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from circuitai.services.account_service import AccountService
            svc = AccountService(self.db)
            accounts = svc.list_accounts()

            lines = ["[bold green]Bank Accounts[/bold green]\n"]
            for a in accounts:
                last4 = f"****{a.last_four}" if a.last_four else ""
                lines.append(f"  {a.name:<18} {last4:>8}  {dollars(a.balance_cents):>12}")
            if not accounts:
                lines.append("  [dim]No accounts[/dim]")
            lines.append(f"\n  [bold]Total: {dollars(svc.get_total_balance())}[/bold]")
            self.update("\n".join(lines))
        except Exception as e:
            self.update(f"[red]Error: {e}[/red]")


class CardsPanel(Static):
    """Credit cards panel."""

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from circuitai.services.card_service import CardService
            svc = CardService(self.db)
            cards = svc.list_cards()

            lines = ["[bold red]Credit Cards[/bold red]\n"]
            for c in cards:
                lines.append(f"  {c.name:<18} {dollars(c.balance_cents):>10} / {dollars(c.credit_limit_cents)}")
            if not cards:
                lines.append("  [dim]No credit cards[/dim]")
            self.update("\n".join(lines))
        except Exception as e:
            self.update(f"[red]Error: {e}[/red]")


class DeadlinesPanel(Static):
    """Deadlines panel."""

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from circuitai.services.deadline_service import DeadlineService
            svc = DeadlineService(self.db)
            overdue = svc.get_overdue()
            upcoming = svc.get_upcoming(within_days=14)

            lines = ["[bold magenta]Deadlines[/bold magenta]\n"]
            for d in overdue[:3]:
                lines.append(f"  [red][!] {d.title} — OVERDUE ({d.due_date})[/red]")
            for d in upcoming[:5]:
                lines.append(f"  {d.title:<25} {d.due_date}  ({d.days_until}d)")
            if not overdue and not upcoming:
                lines.append("  [dim]No upcoming deadlines[/dim]")
            self.update("\n".join(lines))
        except Exception as e:
            self.update(f"[red]Error: {e}[/red]")


class ActivitiesPanel(Static):
    """Kids activities panel."""

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from circuitai.services.activity_service import ActivityService
            svc = ActivityService(self.db)
            activities = svc.list_activities()

            lines = ["[bold blue]Activities[/bold blue]\n"]
            for a in activities[:8]:
                child = ""
                if a.child_id:
                    try:
                        c = svc.get_child(a.child_id)
                        child = f" ({c.name})"
                    except Exception:
                        pass
                schedule = f" — {a.schedule}" if a.schedule else ""
                lines.append(f"  {a.name}{child}{schedule}")
            if not activities:
                lines.append("  [dim]No activities[/dim]")
            self.update("\n".join(lines))
        except Exception as e:
            self.update(f"[red]Error: {e}[/red]")


class InvestmentsPanel(Static):
    """Investments panel."""

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def on_mount(self) -> None:
        self.refresh_data()

    def refresh_data(self) -> None:
        try:
            from circuitai.services.investment_service import InvestmentService
            svc = InvestmentService(self.db)
            investments = svc.list_investments()

            lines = ["[bold cyan]Investments[/bold cyan]\n"]
            for i in investments[:8]:
                gain = f"{i.gain_loss_pct:+.1f}%"
                lines.append(f"  {i.name:<20} {dollars(i.current_value_cents):>12} {gain:>8}")
            if not investments:
                lines.append("  [dim]No investments[/dim]")
            total = svc.get_total_value()
            lines.append(f"\n  [bold]Total: {dollars(total)}[/bold]")
            self.update("\n".join(lines))
        except Exception as e:
            self.update(f"[red]Error: {e}[/red]")


class CircuitDashboard(App):
    """CircuitAI Textual TUI Dashboard."""

    CSS = """
    Screen {
        layout: grid;
        grid-size: 2 4;
        grid-gutter: 1;
        padding: 1;
    }

    .panel {
        border: solid $primary;
        padding: 1;
        height: auto;
        min-height: 8;
    }

    #summary-panel {
        column-span: 2;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
    ]

    def __init__(self, db: DatabaseConnection, **kwargs) -> None:
        super().__init__(**kwargs)
        self.db = db

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield SummaryPanel(self.db, id="summary-panel", classes="panel")
        yield AccountsPanel(self.db, classes="panel")
        yield CardsPanel(self.db, classes="panel")
        yield BillsPanel(self.db, classes="panel")
        yield DeadlinesPanel(self.db, classes="panel")
        yield InvestmentsPanel(self.db, classes="panel")
        yield ActivitiesPanel(self.db, classes="panel")
        yield Footer()

    def action_refresh(self) -> None:
        """Refresh all panels."""
        for widget in self.query(".panel"):
            if hasattr(widget, "refresh_data"):
                widget.refresh_data()  # type: ignore[attr-defined]
