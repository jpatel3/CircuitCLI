"""Tests for free-form text parser."""

import tempfile
from pathlib import Path

import pytest

from circuitai.core.database import DatabaseConnection
from circuitai.core.migrations import initialize_database
from circuitai.services.text_parser import TextParser


@pytest.fixture
def db():
    with tempfile.TemporaryDirectory() as d:
        conn = DatabaseConnection(db_path=Path(d) / "test.db")
        conn.connect()
        initialize_database(conn)
        yield conn
        conn.close()


@pytest.fixture
def parser(db):
    return TextParser(db)


class TestTextParser:
    def test_parse_bill(self, parser):
        result = parser.parse("JCPL electric bill $142 due March 15")
        assert result["entity_type"] == "bill"
        assert result["fields"]["amount_cents"] == 14200
        assert result["fields"]["date"] is not None
        assert result["confidence"] > 0.3

    def test_parse_amount_dollars(self, parser):
        result = parser.parse("something costs $89.99")
        assert result["fields"]["amount_cents"] == 8999

    def test_parse_amount_no_cents(self, parser):
        result = parser.parse("payment of $350")
        assert result["fields"]["amount_cents"] == 35000

    def test_parse_date_month_day(self, parser):
        result = parser.parse("due March 15")
        assert result["fields"]["date"] is not None
        assert "-03-15" in result["fields"]["date"]

    def test_parse_date_tomorrow(self, parser):
        result = parser.parse("due tomorrow")
        assert result["fields"]["date"] is not None

    def test_parse_date_on_day(self, parser):
        result = parser.parse("due on the 5th")
        assert result["fields"]["date"] is not None

    def test_parse_payment(self, parser):
        result = parser.parse("paid electric bill $142")
        assert result["entity_type"] == "payment"
        assert result["fields"]["amount_cents"] == 14200

    def test_parse_activity(self, parser):
        result = parser.parse("hockey practice for Jake")
        assert result["entity_type"] == "activity"

    def test_parse_deadline(self, parser):
        result = parser.parse("dentist appointment March 20")
        assert result["entity_type"] == "deadline"

    def test_parse_recurrence(self, parser):
        result = parser.parse("xfinity internet $89.99 monthly")
        assert result["fields"]["frequency"] == "monthly"

    def test_low_confidence_garbage(self, parser):
        result = parser.parse("hello world")
        assert result["confidence"] < 0.5
