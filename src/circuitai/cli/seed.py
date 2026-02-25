"""Seed data command — optional pre-population of example data."""

from __future__ import annotations

import click

from circuitai.cli.main import CircuitContext, pass_context


@click.command("seed")
@click.option(
    "--profile",
    type=click.Choice(["demo", "minimal"]),
    default="demo",
    help="Data profile: demo (full example set) or minimal (just categories).",
)
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation prompt.")
@pass_context
def seed_cmd(ctx: CircuitContext, profile: str, yes: bool) -> None:
    """Populate database with example data for testing or getting started."""
    db = ctx.get_db()

    if ctx.json_mode:
        result = _run_seed(db, profile)
        ctx.formatter.json(result)
        return

    if not yes:
        click.confirm(
            f"This will populate your database with '{profile}' example data. Continue?",
            abort=True,
        )

    result = _run_seed(db, profile)

    ctx.formatter.success(f"Seed complete ({profile} profile):")
    for entity, count in result["counts"].items():
        if count > 0:
            ctx.formatter.print(f"  {entity}: {count} records")


def _run_seed(db, profile: str) -> dict:
    """Run the seed for the given profile."""
    if profile == "minimal":
        return _seed_minimal(db)
    return _seed_demo(db)


def _seed_minimal(db) -> dict:
    """Seed with just structure — no example records."""
    return {"profile": "minimal", "counts": {}}


def _seed_demo(db) -> dict:
    """Seed with a full set of demo data."""
    from circuitai.services.account_service import AccountService
    from circuitai.services.activity_service import ActivityService
    from circuitai.services.bill_service import BillService
    from circuitai.services.card_service import CardService
    from circuitai.services.deadline_service import DeadlineService
    from circuitai.services.investment_service import InvestmentService
    from circuitai.services.mortgage_service import MortgageService

    counts = {}

    # --- Bank Accounts ---
    acct_svc = AccountService(db)
    accounts = [
        {"name": "Chase Checking", "institution": "Chase", "account_type": "checking",
         "last_four": "4321", "balance_cents": 520000},
        {"name": "Chase Savings", "institution": "Chase", "account_type": "savings",
         "last_four": "4322", "balance_cents": 1500000},
        {"name": "BofA Checking", "institution": "Bank of America", "account_type": "checking",
         "last_four": "8765", "balance_cents": 1240000},
        {"name": "Wealthfront Cash", "institution": "Wealthfront", "account_type": "savings",
         "last_four": "9900", "balance_cents": 2500000},
    ]
    for a in accounts:
        acct_svc.add_account(**a)
    counts["accounts"] = len(accounts)

    # --- Credit Cards ---
    card_svc = CardService(db)
    cards = [
        {"name": "Amex Platinum", "institution": "American Express",
         "last_four": "1001", "credit_limit_cents": 1000000, "balance_cents": 120500},
        {"name": "Citi Double Cash", "institution": "Citi",
         "last_four": "2002", "credit_limit_cents": 500000, "balance_cents": 89000},
        {"name": "BofA Cash Rewards", "institution": "Bank of America",
         "last_four": "3003", "credit_limit_cents": 800000, "balance_cents": 45000},
    ]
    for c in cards:
        card_svc.add_card(**c)
    counts["cards"] = len(cards)

    # --- Bills ---
    bill_svc = BillService(db)
    bills = [
        {"name": "JCPL Electric", "provider": "JCPL", "category": "electricity",
         "amount_cents": 14200, "due_day": 15, "frequency": "monthly"},
        {"name": "American Water", "provider": "American Water", "category": "water",
         "amount_cents": 6750, "due_day": 20, "frequency": "monthly"},
        {"name": "Elizabethtown Gas", "provider": "Elizabethtown Gas", "category": "gas",
         "amount_cents": 9500, "due_day": 12, "frequency": "monthly"},
        {"name": "Xfinity Internet", "provider": "Xfinity", "category": "internet",
         "amount_cents": 8999, "due_day": 5, "frequency": "monthly"},
        {"name": "Municipality Tax", "provider": "Municipality", "category": "tax",
         "amount_cents": 250000, "due_day": 1, "frequency": "quarterly"},
        {"name": "HOA Fees", "provider": "HOA", "category": "housing",
         "amount_cents": 360000, "due_day": 1, "frequency": "yearly"},
        {"name": "Auto Insurance", "provider": "State Farm", "category": "insurance",
         "amount_cents": 180000, "due_day": 15, "frequency": "yearly"},
        {"name": "Home Insurance", "provider": "State Farm", "category": "insurance",
         "amount_cents": 240000, "due_day": 1, "frequency": "yearly"},
        {"name": "Umbrella Insurance", "provider": "State Farm", "category": "insurance",
         "amount_cents": 50000, "due_day": 1, "frequency": "yearly"},
        {"name": "Life Insurance", "provider": "Northwestern Mutual", "category": "insurance",
         "amount_cents": 120000, "due_day": 10, "frequency": "yearly"},
    ]
    for b in bills:
        bill_svc.add_bill(**b)
    counts["bills"] = len(bills)

    # --- Mortgage ---
    mtg_svc = MortgageService(db)
    mtg_svc.add_mortgage(
        name="Primary Residence",
        lender="Townee Mortgage",
        original_amount_cents=45000000,
        balance_cents=38000000,
        interest_rate_bps=688,
        monthly_payment_cents=295000,
        start_date="2022-06-01",
        term_months=360,
    )
    counts["mortgages"] = 1

    # --- Investments ---
    inv_svc = InvestmentService(db)
    investments = [
        {"name": "Wealthfront", "institution": "Wealthfront", "account_type": "brokerage",
         "current_value_cents": 5200000, "cost_basis_cents": 4800000},
        {"name": "Titan Invest", "institution": "Titan", "account_type": "brokerage",
         "current_value_cents": 3100000, "cost_basis_cents": 2900000},
        {"name": "Schwab Fund", "institution": "Charles Schwab", "account_type": "brokerage",
         "current_value_cents": 2800000, "cost_basis_cents": 2500000},
        {"name": "Robinhood", "institution": "Robinhood", "account_type": "brokerage",
         "current_value_cents": 1500000, "cost_basis_cents": 1200000},
        {"name": "401(k)", "institution": "Fidelity", "account_type": "401k",
         "current_value_cents": 15000000, "cost_basis_cents": 12000000},
        {"name": "Kids 529 Plan", "institution": "Vanguard", "account_type": "529",
         "current_value_cents": 4500000, "cost_basis_cents": 4000000},
    ]
    for inv in investments:
        inv_svc.add_investment(**inv)
    counts["investments"] = len(investments)

    # --- Children & Activities ---
    act_svc = ActivityService(db)
    child1 = act_svc.add_child("Jake", birth_date="2017-06-15")
    child2 = act_svc.add_child("Emma", birth_date="2019-03-22")
    counts["children"] = 2

    activities = [
        {"name": "Hockey", "child_id": child1.id, "sport_or_type": "Hockey",
         "provider": "Local Ice Rink", "season": "Fall/Winter",
         "cost_cents": 35000, "frequency": "weekly",
         "schedule": "Tue/Thu 5-6pm", "location": "Ice Arena"},
        {"name": "Soccer", "child_id": child1.id, "sport_or_type": "Soccer",
         "provider": "Town League", "season": "Spring",
         "cost_cents": 15000, "frequency": "weekly",
         "schedule": "Mon/Wed 4-5pm", "location": "Fields Park"},
        {"name": "Gymnastics", "child_id": child2.id, "sport_or_type": "Gymnastics",
         "provider": "YMCA", "season": "Year-round",
         "cost_cents": 20000, "frequency": "weekly",
         "schedule": "Mon/Wed 5:30-6:30pm", "location": "YMCA"},
        {"name": "Tennis", "child_id": child2.id, "sport_or_type": "Tennis",
         "provider": "Tennis Club", "season": "Summer",
         "cost_cents": 25000, "frequency": "weekly",
         "schedule": "Sat 10-11am", "location": "Tennis Club"},
    ]
    for a in activities:
        act_svc.add_activity(**a)
    counts["activities"] = len(activities)

    # --- Deadlines ---
    dl_svc = DeadlineService(db)
    deadlines = [
        {"title": "File tax return", "due_date": "2026-04-15",
         "priority": "high", "category": "tax"},
        {"title": "Renew car registration", "due_date": "2026-03-31",
         "priority": "medium", "category": "personal"},
    ]
    for d in deadlines:
        dl_svc.add_deadline(**d)
    counts["deadlines"] = len(deadlines)

    return {"profile": "demo", "counts": counts}
