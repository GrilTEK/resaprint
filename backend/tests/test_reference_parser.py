from datetime import date
from decimal import Decimal

import pytest

from app.services.parser_registry import ParserError
from app.services.parsers.reference_booking_com import ReferenceBookingComParser

SAMPLE_SUBJECT = "New booking confirmation - Booking.com"

SAMPLE_BODY = """\
Hello,

You have a new reservation.

Guest name: Jane Doe
Check-in: 15-08-2026
Check-out: 18-08-2026
Booking number: 1234567890
Room type: Double Room
Total price: EUR 270.00

Thank you.
"""


def test_can_parse_matches_expected_subject():
    parser = ReferenceBookingComParser()
    assert parser.can_parse(SAMPLE_SUBJECT, SAMPLE_BODY, "text/plain")


def test_can_parse_rejects_unrelated_subject():
    parser = ReferenceBookingComParser()
    assert not parser.can_parse("Your Amazon order has shipped", SAMPLE_BODY, "text/plain")


def test_parse_extracts_all_fields():
    parser = ReferenceBookingComParser()
    result = parser.parse(SAMPLE_SUBJECT, SAMPLE_BODY, "text/plain")

    assert result.guest_name == "Jane Doe"
    assert result.checkin == date(2026, 8, 15)
    assert result.checkout == date(2026, 8, 18)
    assert result.external_ref == "1234567890"
    assert result.room_type == "Double Room"
    assert result.price_total == Decimal("270.00")
    assert result.price_currency == "EUR"
    assert result.source_channel == "booking_com"


def test_parse_raises_when_required_fields_missing():
    parser = ReferenceBookingComParser()
    with pytest.raises(ParserError):
        parser.parse(SAMPLE_SUBJECT, "Guest name: Jane Doe\n", "text/plain")
