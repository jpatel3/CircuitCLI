"""Tests for subscription detection and management."""

import tempfile
from datetime import date, timedelta
from pathlib import Path

import pytest
from click.testing import CliRunner

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.models.subscription import Subscription, SubscriptionRepository
from circuitai.services.subscription_service import (
    SubscriptionService,
    normalize_vendor,
)


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


@pytest.fixture
def repo(db):
    return SubscriptionRepository(db)


@pytest.fixture
def svc(db):
    return SubscriptionService(db)


def _seed_recurring_transactions(
    db,
    vendor: str,
    amount_cents: int,
    count: int = 5,
    interval_days: int = 30,
    table: str = "account_transactions",
):
    """Seed recurring transactions at regular intervals for detection testing."""
    from circuitai.models.base import new_id

    today = date.today()
    for i in range(count):
        txn_date = (today - timedelta(days=interval_days * (count - 1 - i))).isoformat()
        if table == "account_transactions":
            # Account transactions: debits are negative
            db.execute(
                "INSERT INTO account_transactions (id, account_id, description, amount_cents, transaction_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_id(), "acct-1", vendor, -abs(amount_cents), txn_date),
            )
        else:
            # Card transactions: charges are positive
            db.execute(
                "INSERT INTO card_transactions (id, card_id, description, amount_cents, transaction_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_id(), "card-1", vendor, abs(amount_cents), txn_date),
            )
    db.commit()


def _seed_account(db, account_id="acct-1"):
    """Seed a minimal account for FK constraints."""
    from circuitai.models.base import new_id

    db.execute(
        "INSERT OR IGNORE INTO accounts (id, name, institution) VALUES (?, ?, ?)",
        (account_id, "Test Account", "Test Bank"),
    )
    db.commit()


def _seed_card(db, card_id="card-1"):
    """Seed a minimal card for FK constraints."""
    db.execute(
        "INSERT OR IGNORE INTO cards (id, name, institution) VALUES (?, ?, ?)",
        (card_id, "Test Card", "Test Bank"),
    )
    db.commit()


# ── Model Tests ───────────────────────────────────────────────────


class TestSubscriptionModel:
    def test_creation(self):
        sub = Subscription(name="Netflix", amount_cents=1599, frequency="monthly")
        assert sub.name == "Netflix"
        assert sub.amount_cents == 1599
        assert sub.frequency == "monthly"
        assert sub.id  # UUID assigned

    def test_to_row_from_row(self, db):
        sub = Subscription(
            name="Spotify",
            amount_cents=999,
            frequency="monthly",
            is_active=True,
            confidence=85,
        )
        row_data = sub.to_row()
        assert row_data["is_active"] == 1  # bool → int

        # Insert and retrieve
        repo = SubscriptionRepository(db)
        repo.insert(sub)
        fetched = repo.get(sub.id)
        assert fetched.name == "Spotify"
        assert fetched.is_active is True  # int → bool
        assert fetched.confidence == 85

    def test_confidence_score(self):
        sub = Subscription(name="Test", confidence=75)
        assert sub.confidence_score == 0.75

    def test_confidence_score_zero(self):
        sub = Subscription(name="Test", confidence=0)
        assert sub.confidence_score == 0.0

    def test_monthly_cost_weekly(self):
        sub = Subscription(name="Test", amount_cents=700, frequency="weekly")
        assert sub.monthly_cost_cents == int(700 * 52 / 12)

    def test_monthly_cost_monthly(self):
        sub = Subscription(name="Test", amount_cents=999, frequency="monthly")
        assert sub.monthly_cost_cents == 999

    def test_monthly_cost_quarterly(self):
        sub = Subscription(name="Test", amount_cents=3000, frequency="quarterly")
        assert sub.monthly_cost_cents == 1000

    def test_monthly_cost_yearly(self):
        sub = Subscription(name="Test", amount_cents=12000, frequency="yearly")
        assert sub.monthly_cost_cents == 1000

    def test_yearly_cost_weekly(self):
        sub = Subscription(name="Test", amount_cents=700, frequency="weekly")
        assert sub.yearly_cost_cents == 700 * 52

    def test_yearly_cost_monthly(self):
        sub = Subscription(name="Test", amount_cents=999, frequency="monthly")
        assert sub.yearly_cost_cents == 999 * 12

    def test_yearly_cost_quarterly(self):
        sub = Subscription(name="Test", amount_cents=3000, frequency="quarterly")
        assert sub.yearly_cost_cents == 3000 * 4

    def test_yearly_cost_yearly(self):
        sub = Subscription(name="Test", amount_cents=12000, frequency="yearly")
        assert sub.yearly_cost_cents == 12000


# ── Repository Tests ──────────────────────────────────────────────


class TestSubscriptionRepository:
    def test_insert_and_get(self, repo):
        sub = Subscription(name="Netflix", amount_cents=1599)
        repo.insert(sub)
        fetched = repo.get(sub.id)
        assert fetched.name == "Netflix"

    def test_list_all(self, repo):
        repo.insert(Subscription(name="Sub1", amount_cents=100))
        repo.insert(Subscription(name="Sub2", amount_cents=200))
        all_subs = repo.list_all()
        assert len(all_subs) == 2

    def test_find_by_match_pattern_found(self, repo):
        sub = Subscription(name="Netflix", match_pattern="NETFLIX.COM")
        repo.insert(sub)
        found = repo.find_by_match_pattern("NETFLIX.COM")
        assert found is not None
        assert found.id == sub.id

    def test_find_by_match_pattern_not_found(self, repo):
        assert repo.find_by_match_pattern("NONEXISTENT") is None

    def test_find_by_status(self, repo):
        repo.insert(Subscription(name="Active", status="active"))
        repo.insert(Subscription(name="Cancelled", status="cancelled"))
        active = repo.find_by_status("active")
        assert len(active) == 1
        assert active[0].name == "Active"

    def test_get_upcoming(self, repo):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        next_month = (date.today() + timedelta(days=30)).isoformat()

        repo.insert(Subscription(name="Soon", next_charge_date=tomorrow, status="active"))
        repo.insert(Subscription(name="Later", next_charge_date=next_month, status="active"))

        upcoming = repo.get_upcoming(within_days=7)
        assert len(upcoming) == 1
        assert upcoming[0].name == "Soon"

    def test_get_all_match_patterns(self, repo):
        repo.insert(Subscription(name="A", match_pattern="NETFLIX.COM"))
        repo.insert(Subscription(name="B", match_pattern="SPOTIFY.COM"))
        patterns = repo.get_all_match_patterns()
        assert patterns == {"NETFLIX.COM", "SPOTIFY.COM"}


# ── Normalization Tests ───────────────────────────────────────────


class TestNormalizeVendor:
    def test_strips_ach_debit(self):
        assert normalize_vendor("ACH DEBIT NETFLIX.COM") == "NETFLIX.COM"

    def test_strips_online_payment(self):
        assert normalize_vendor("ONLINE PAYMENT SPOTIFY PREMIUM") == "SPOTIFY PREMIUM"

    def test_strips_recurring_payment(self):
        assert normalize_vendor("RECURRING PAYMENT ADOBE CREATIVE") == "ADOBE CREATIVE"

    def test_strips_trailing_numbers(self):
        assert normalize_vendor("NETFLIX.COM 12345678") == "NETFLIX.COM"

    def test_strips_trailing_date(self):
        assert normalize_vendor("SPOTIFY PREMIUM 02/15") == "SPOTIFY PREMIUM"

    def test_normalizes_whitespace(self):
        assert normalize_vendor("  NETFLIX   COM  ") == "NETFLIX COM"

    def test_returns_uppercase(self):
        assert normalize_vendor("netflix.com") == "NETFLIX.COM"

    def test_strips_automatic_payment(self):
        assert normalize_vendor("AUTOMATIC PAYMENT GEICO INSURANCE") == "GEICO INSURANCE"

    def test_strips_debit_card_purchase(self):
        assert normalize_vendor("DEBIT CARD PURCHASE AMAZON PRIME") == "AMAZON PRIME"

    def test_strips_visa(self):
        assert normalize_vendor("VISA HULU LLC") == "HULU LLC"

    def test_no_prefix_passthrough(self):
        assert normalize_vendor("NETFLIX.COM") == "NETFLIX.COM"


# ── Detection Algorithm Tests ─────────────────────────────────────


class TestDetectionAlgorithm:
    def test_monthly_charges_detected(self, db, svc):
        _seed_account(db)
        _seed_recurring_transactions(db, "NETFLIX.COM", 1599, count=5, interval_days=30)
        detected = svc.detect_subscriptions()
        assert len(detected) == 1
        assert detected[0].match_pattern == "NETFLIX.COM"
        assert detected[0].frequency == "monthly"
        assert detected[0].confidence >= 60

    def test_too_few_charges_not_detected(self, db, svc):
        _seed_account(db)
        _seed_recurring_transactions(db, "ONETIME VENDOR", 5000, count=2, interval_days=30)
        detected = svc.detect_subscriptions()
        assert len(detected) == 0

    def test_irregular_intervals_not_detected(self, db, svc):
        """Random intervals that don't fit any bucket → not detected."""
        from circuitai.models.base import new_id

        _seed_account(db)
        today = date.today()
        # Create 4 transactions at wildly varying intervals
        for days_ago in [0, 15, 42, 55]:
            txn_date = (today - timedelta(days=days_ago)).isoformat()
            db.execute(
                "INSERT INTO account_transactions (id, account_id, description, amount_cents, transaction_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_id(), "acct-1", "RANDOM VENDOR", -1000, txn_date),
            )
        db.commit()

        detected = svc.detect_subscriptions()
        # Should not be detected since intervals are too inconsistent
        random_matches = [d for d in detected if d.match_pattern == "RANDOM VENDOR"]
        assert len(random_matches) == 0

    def test_existing_bill_excluded(self, db, svc):
        """Vendor matching an existing bill's match_patterns should be excluded."""
        _seed_account(db)
        _seed_recurring_transactions(db, "JCPL ELECTRIC", 14200, count=5, interval_days=30)

        # Add a bill with matching pattern
        from circuitai.services.bill_service import BillService

        bill_svc = BillService(db)
        bill_svc.add_bill(name="JCPL Electric", provider="JCPL ELECTRIC", amount_cents=14200)

        detected = svc.detect_subscriptions()
        jcpl_matches = [d for d in detected if "JCPL" in d.match_pattern]
        assert len(jcpl_matches) == 0

    def test_existing_subscription_excluded(self, db, svc):
        """Vendor matching an existing subscription should be excluded (idempotent)."""
        _seed_account(db)
        _seed_recurring_transactions(db, "SPOTIFY PREMIUM", 999, count=5, interval_days=30)

        # First detection
        detected1 = svc.detect_subscriptions()
        spotify = [d for d in detected1 if "SPOTIFY" in d.match_pattern]
        assert len(spotify) == 1

        # Confirm it
        svc.confirm_detected(spotify)

        # Second detection — should be excluded
        detected2 = svc.detect_subscriptions()
        spotify2 = [d for d in detected2 if "SPOTIFY" in d.match_pattern]
        assert len(spotify2) == 0

    def test_consistent_amounts_high_confidence(self, db, svc):
        """Same amount every time → high amount consistency score."""
        _seed_account(db)
        _seed_recurring_transactions(db, "FIXED AMOUNT SVC", 999, count=6, interval_days=30)
        detected = svc.detect_subscriptions()
        matches = [d for d in detected if "FIXED AMOUNT" in d.match_pattern]
        assert len(matches) == 1
        assert matches[0].confidence >= 70

    def test_varying_amounts_lower_confidence(self, db, svc):
        """Amounts varying significantly → lower confidence than consistent amounts."""
        from circuitai.models.base import new_id

        _seed_account(db)
        today = date.today()
        amounts = [1000, 1500, 800, 2000, 1200]  # highly variable
        for i, amt in enumerate(amounts):
            txn_date = (today - timedelta(days=30 * (len(amounts) - 1 - i))).isoformat()
            db.execute(
                "INSERT INTO account_transactions (id, account_id, description, amount_cents, transaction_date) "
                "VALUES (?, ?, ?, ?, ?)",
                (new_id(), "acct-1", "VARIABLE VENDOR", -amt, txn_date),
            )
        db.commit()

        detected = svc.detect_subscriptions()
        matches = [d for d in detected if "VARIABLE" in d.match_pattern]
        # Variable amounts should have lower confidence (no amount consistency points)
        if matches:
            assert matches[0].confidence < 80

    def test_card_and_account_transactions_grouped(self, db, svc):
        """Same vendor on both card and account transactions → grouped together."""
        from circuitai.models.base import new_id

        _seed_account(db)
        _seed_card(db)
        today = date.today()

        # Seed alternating: months 1,3,5 on account, months 2,4,6 on card
        for i in range(6):
            txn_date = (today - timedelta(days=30 * (5 - i))).isoformat()
            if i % 2 == 0:
                db.execute(
                    "INSERT INTO account_transactions (id, account_id, description, amount_cents, transaction_date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (new_id(), "acct-1", "MIXED VENDOR", -999, txn_date),
                )
            else:
                db.execute(
                    "INSERT INTO card_transactions (id, card_id, description, amount_cents, transaction_date) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (new_id(), "card-1", "MIXED VENDOR", 999, txn_date),
                )
        db.commit()

        detected = svc.detect_subscriptions()
        matches = [d for d in detected if "MIXED VENDOR" in d.match_pattern]
        assert len(matches) == 1

    def test_weekly_charges_detected(self, db, svc):
        _seed_account(db)
        _seed_recurring_transactions(db, "WEEKLY SERVICE", 500, count=6, interval_days=7)
        detected = svc.detect_subscriptions()
        matches = [d for d in detected if "WEEKLY" in d.match_pattern]
        assert len(matches) == 1
        assert matches[0].frequency == "weekly"

    def test_quarterly_charges_detected(self, db, svc):
        _seed_account(db)
        _seed_recurring_transactions(db, "QUARTERLY SVC", 5000, count=4, interval_days=90)
        detected = svc.detect_subscriptions()
        matches = [d for d in detected if "QUARTERLY" in d.match_pattern]
        assert len(matches) == 1
        assert matches[0].frequency == "quarterly"

    def test_next_charge_date_predicted(self, db, svc):
        _seed_account(db)
        _seed_recurring_transactions(db, "PREDICTABLE SVC", 999, count=5, interval_days=30)
        detected = svc.detect_subscriptions()
        matches = [d for d in detected if "PREDICTABLE" in d.match_pattern]
        assert len(matches) == 1
        assert matches[0].next_charge_date is not None


# ── Service CRUD Tests ────────────────────────────────────────────


class TestSubscriptionServiceCRUD:
    def test_add_subscription(self, svc):
        sub = svc.add_subscription(name="Netflix", amount_cents=1599, frequency="monthly")
        assert sub.name == "Netflix"
        assert sub.source == "manual"
        assert sub.match_pattern == "NETFLIX"

    def test_add_validates_name(self, svc):
        from circuitai.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="name"):
            svc.add_subscription(name="", amount_cents=100)

    def test_add_validates_amount(self, svc):
        from circuitai.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="negative"):
            svc.add_subscription(name="Bad", amount_cents=-100)

    def test_add_validates_frequency(self, svc):
        from circuitai.core.exceptions import ValidationError

        with pytest.raises(ValidationError, match="frequency"):
            svc.add_subscription(name="Bad", frequency="biweekly")

    def test_list_subscriptions(self, svc):
        svc.add_subscription(name="Sub1", amount_cents=100)
        svc.add_subscription(name="Sub2", amount_cents=200)
        subs = svc.list_subscriptions()
        assert len(subs) == 2

    def test_cancel_subscription(self, svc):
        sub = svc.add_subscription(name="To Cancel", amount_cents=999)
        cancelled = svc.cancel_subscription(sub.id)
        assert cancelled.status == "cancelled"

    def test_get_summary(self, svc):
        svc.add_subscription(name="Monthly", amount_cents=1000, frequency="monthly")
        svc.add_subscription(name="Yearly", amount_cents=12000, frequency="yearly")
        summary = svc.get_summary()
        assert summary["total_active"] == 2
        # Monthly: 1000 + 12000/12 = 2000
        assert summary["monthly_total_cents"] == 2000
        # Yearly: 1000*12 + 12000 = 24000
        assert summary["yearly_total_cents"] == 24000

    def test_get_summary_by_category(self, svc):
        svc.add_subscription(name="A", amount_cents=500, category="streaming")
        svc.add_subscription(name="B", amount_cents=1000, category="streaming")
        svc.add_subscription(name="C", amount_cents=2000, category="software")
        summary = svc.get_summary()
        assert summary["by_category"]["streaming"] == 1500
        assert summary["by_category"]["software"] == 2000

    def test_get_summary_by_frequency(self, svc):
        svc.add_subscription(name="A", amount_cents=500, frequency="monthly")
        svc.add_subscription(name="B", amount_cents=1000, frequency="monthly")
        svc.add_subscription(name="C", amount_cents=2000, frequency="yearly")
        summary = svc.get_summary()
        assert summary["by_frequency"]["monthly"] == 2
        assert summary["by_frequency"]["yearly"] == 1

    def test_confirm_detected_idempotent(self, svc):
        sub = Subscription(
            name="Test",
            match_pattern="TEST PATTERN",
            amount_cents=999,
            source="detected",
        )
        count1 = svc.confirm_detected([sub])
        assert count1 == 1

        # Same pattern again — should not duplicate
        sub2 = Subscription(
            name="Test",
            match_pattern="TEST PATTERN",
            amount_cents=999,
            source="detected",
        )
        count2 = svc.confirm_detected([sub2])
        assert count2 == 0

    def test_update_subscription(self, svc):
        sub = svc.add_subscription(name="Old Name", amount_cents=999)
        updated = svc.update_subscription(sub.id, name="New Name", amount_cents=1299)
        assert updated.name == "New Name"
        assert updated.amount_cents == 1299


# ── CLI Tests ─────────────────────────────────────────────────────


class TestSubscriptionsCLI:
    @pytest.fixture
    def cli_runner(self, db):
        """Return a CliRunner that patches CircuitContext.get_db to use the temp DB."""
        from unittest.mock import patch

        from circuitai.cli.main import CircuitContext

        runner = CliRunner()

        def patched_get_db(self_ctx):
            self_ctx._db = db
            return db

        with patch.object(CircuitContext, "get_db", patched_get_db):
            yield runner

    def test_list_empty(self, cli_runner):
        from circuitai.cli.main import cli

        result = cli_runner.invoke(cli, ["subscriptions", "list"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "No subscriptions" in result.output

    def test_list_json(self, db, cli_runner):
        from circuitai.cli.main import cli

        svc = SubscriptionService(db)
        svc.add_subscription(name="Netflix", amount_cents=1599)
        result = cli_runner.invoke(cli, ["--json", "subscriptions", "list"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Netflix" in result.output

    def test_list_with_data(self, db, cli_runner):
        from circuitai.cli.main import cli

        svc = SubscriptionService(db)
        svc.add_subscription(name="Netflix", amount_cents=1599)
        result = cli_runner.invoke(cli, ["subscriptions", "list"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Netflix" in result.output

    def test_add_interactive(self, cli_runner):
        from circuitai.cli.main import cli

        result = cli_runner.invoke(
            cli,
            ["subscriptions", "add"],
            catch_exceptions=False,
            input="Spotify\n9.99\nmonthly\n",
        )
        assert result.exit_code == 0
        assert "Spotify" in result.output

    def test_summary(self, db, cli_runner):
        from circuitai.cli.main import cli

        svc = SubscriptionService(db)
        svc.add_subscription(name="Netflix", amount_cents=1599, frequency="monthly")
        svc.add_subscription(name="Adobe", amount_cents=5499, frequency="monthly")
        result = cli_runner.invoke(cli, ["subscriptions", "summary"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "Monthly total" in result.output

    def test_summary_json(self, db, cli_runner):
        from circuitai.cli.main import cli

        svc = SubscriptionService(db)
        svc.add_subscription(name="Netflix", amount_cents=1599)
        result = cli_runner.invoke(cli, ["--json", "subscriptions", "summary"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "total_active" in result.output

    def test_detect_no_data(self, cli_runner):
        from circuitai.cli.main import cli

        result = cli_runner.invoke(cli, ["subscriptions", "detect"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "No new subscriptions" in result.output

    def test_detect_with_data(self, db, cli_runner):
        from circuitai.cli.main import cli

        _seed_account(db)
        _seed_recurring_transactions(db, "NETFLIX.COM", 1599, count=5, interval_days=30)
        result = cli_runner.invoke(
            cli, ["subscriptions", "detect"], catch_exceptions=False, input="a\n"
        )
        assert result.exit_code == 0
        assert "Confirmed" in result.output or "Detected" in result.output

    def test_cancel_by_id(self, db, cli_runner):
        from circuitai.cli.main import cli

        svc = SubscriptionService(db)
        sub = svc.add_subscription(name="To Cancel", amount_cents=999)
        result = cli_runner.invoke(
            cli, ["subscriptions", "cancel", sub.id], catch_exceptions=False, input="y\n"
        )
        assert result.exit_code == 0
        assert "Cancelled" in result.output
