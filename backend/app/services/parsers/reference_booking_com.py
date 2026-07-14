"""Reference/example parser — illustrative only.

This targets a fabricated, plausible-looking "Booking.com style"
reservation confirmation email layout. It is NOT verified against real
Booking.com traffic and real subject lines/body formats vary and
change over time. It exists to (a) prove the ReservationParser
interface with a concrete implementation and (b) give the test suite a
worked example. Real deployments should create their own field-mapping
profile via the admin UI (see /parsers) for whatever format their
actual channel manager or OTA sends.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal

from app.schemas.parser import ParsedReservation
from app.services.parser_registry import ParserError

_SUBJECT_RE = re.compile(r"New booking.*Booking\.com", re.IGNORECASE)

_GUEST_RE = re.compile(r"^Guest name:\s*(.+)$", re.MULTILINE)
_CHECKIN_RE = re.compile(r"^Check-in:\s*(\d{2}-\d{2}-\d{4})$", re.MULTILINE)
_CHECKOUT_RE = re.compile(r"^Check-out:\s*(\d{2}-\d{2}-\d{4})$", re.MULTILINE)
_BOOKING_NO_RE = re.compile(r"^Booking number:\s*(\S+)$", re.MULTILINE)
_ROOM_RE = re.compile(r"^Room type:\s*(.+)$", re.MULTILINE)
_PRICE_RE = re.compile(r"^Total price:\s*([A-Z]{3})\s*([\d.,]+)$", re.MULTILINE)


class ReferenceBookingComParser:
    slug = "booking_com_reference"

    def can_parse(self, raw_subject: str, raw_body: str, content_type: str) -> bool:
        return _SUBJECT_RE.search(raw_subject) is not None

    def parse(self, raw_subject: str, raw_body: str, content_type: str) -> ParsedReservation:
        guest_match = _GUEST_RE.search(raw_body)
        checkin_match = _CHECKIN_RE.search(raw_body)
        checkout_match = _CHECKOUT_RE.search(raw_body)
        if not guest_match or not checkin_match or not checkout_match:
            raise ParserError("reference booking.com parser: missing required fields")

        booking_match = _BOOKING_NO_RE.search(raw_body)
        room_match = _ROOM_RE.search(raw_body)
        price_match = _PRICE_RE.search(raw_body)

        price_total = None
        price_currency = "EUR"
        if price_match:
            price_currency = price_match.group(1)
            price_total = Decimal(price_match.group(2).replace(",", ""))

        return ParsedReservation(
            external_ref=booking_match.group(1) if booking_match else None,
            source_channel="booking_com",
            guest_name=guest_match.group(1).strip(),
            checkin=datetime.strptime(checkin_match.group(1), "%d-%m-%Y").date(),
            checkout=datetime.strptime(checkout_match.group(1), "%d-%m-%Y").date(),
            room_type=room_match.group(1).strip() if room_match else None,
            price_total=price_total,
            price_currency=price_currency,
        )
