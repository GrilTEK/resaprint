"""Multi-room-line extraction (re.finditer over a room_line_pattern
regex with named groups), built from a real Cubilis/Booking.com
forwarded-reservation email a user shared."""
from decimal import Decimal

from app.models.parser_mapping import ExtractionType, FieldTransform, ParserFieldMapping, ParserFieldMappingField
from app.services.parser_registry import GenericFieldMappingParser

ROOM_LINE_PATTERN = r"^Type:\s*(?P<room_type>.+)$\n(?:.*\n)*?^Guest:.*?Price:\s*(?P<price_total>[\d.]+)"

REAL_SINGLE_ROOM_BODY = """\
new reservation via Booking.com
---------------------------------------------------------------------------

Booking nr. 90000001 (9000000001)
Made by smith john on 2026-07-14 20:38:01
---------------------------------------------------------------------------

Arrival: 2026-07-21
Departure: 2026-07-22
Price: 243.34
---------------------------------------------------------------------------

Type: ECONOMY  DOUBLE ROOM WITH BRAKFAST
Nr. of persons: 2 (2 adults, 0 juniors, 0 babies)
Guest: john smithPrice: 243.34

Guest name: john smith
---------------------------------------------------------------------------
"""

# Synthetic two-room booking, same block structure repeated with
# different room types/prices, to prove finditer picks up every match
# rather than only the first (which plain re.search would do).
TWO_ROOM_BODY = """\
new reservation via Booking.com
---------------------------------------------------------------------------

Booking nr. 99999999 (1111111111)
Arrival: 2026-08-01
Departure: 2026-08-03
---------------------------------------------------------------------------

Type: ECONOMY DOUBLE ROOM WITH BREAKFAST
Nr. of persons: 2 (2 adults, 0 juniors, 0 babies)
Guest: jane doePrice: 150.00

Guest name: jane doe
---------------------------------------------------------------------------

Type: DELUXE SUITE
Nr. of persons: 2 (2 adults, 0 juniors, 0 babies)
Guest: jane doePrice: 320.50

Guest name: jane doe
---------------------------------------------------------------------------
"""


def _mapping_with_room_lines(pattern: str, body_regex_fields: list[ParserFieldMappingField]) -> ParserFieldMapping:
    mapping = ParserFieldMapping(profile_slug="booking_com_cubilis", is_active=True, room_line_pattern=pattern)
    mapping.fields = body_regex_fields
    return mapping


def _guest_name_field() -> ParserFieldMappingField:
    return ParserFieldMappingField(
        label="Guest name",
        target_field="guest_name",
        extraction_type=ExtractionType.regex,
        pattern=r"^Guest name:\s*(.+)$",
        group_index=1,
        transform=FieldTransform.none,
        is_required=True,
    )


def _checkin_field() -> ParserFieldMappingField:
    return ParserFieldMappingField(
        label="Arrival",
        target_field="checkin",
        extraction_type=ExtractionType.regex,
        pattern=r"^Arrival:\s*(\d{4}-\d{2}-\d{2})",
        group_index=1,
        transform=FieldTransform.parse_date_iso,
        is_required=True,
    )


def _checkout_field() -> ParserFieldMappingField:
    return ParserFieldMappingField(
        label="Departure",
        target_field="checkout",
        extraction_type=ExtractionType.regex,
        pattern=r"^Departure:\s*(\d{4}-\d{2}-\d{2})",
        group_index=1,
        transform=FieldTransform.parse_date_iso,
        is_required=True,
    )


def test_single_room_line_extracted_from_real_email():
    mapping = _mapping_with_room_lines(
        ROOM_LINE_PATTERN, [_guest_name_field(), _checkin_field(), _checkout_field()]
    )
    parser = GenericFieldMappingParser(mapping)

    result = parser.parse("Fwd: New reservation via Booking.com", REAL_SINGLE_ROOM_BODY, "text/plain")

    assert len(result.room_lines) == 1
    assert result.room_lines[0].room_type == "ECONOMY  DOUBLE ROOM WITH BRAKFAST"
    assert result.room_lines[0].price_total == Decimal("243.34")


def test_multiple_room_lines_all_captured_not_just_first():
    mapping = _mapping_with_room_lines(
        ROOM_LINE_PATTERN, [_guest_name_field(), _checkin_field(), _checkout_field()]
    )
    # The scalar fields still need a guest_name line for the multi-room body.
    mapping.fields[0].pattern = r"^Guest name:\s*(.+)$"
    parser = GenericFieldMappingParser(mapping)

    body_with_guest_name = TWO_ROOM_BODY + "Guest name: jane doe\n"
    result = parser.parse("New reservation via Booking.com", body_with_guest_name, "text/plain")

    assert len(result.room_lines) == 2
    assert result.room_lines[0].room_type == "ECONOMY DOUBLE ROOM WITH BREAKFAST"
    assert result.room_lines[0].price_total == Decimal("150.00")
    assert result.room_lines[1].room_type == "DELUXE SUITE"
    assert result.room_lines[1].price_total == Decimal("320.50")


def test_no_room_line_pattern_yields_empty_list():
    mapping = ParserFieldMapping(profile_slug="no_room_lines", is_active=True, room_line_pattern=None)
    mapping.fields = [_guest_name_field(), _checkin_field(), _checkout_field()]
    parser = GenericFieldMappingParser(mapping)

    result = parser.parse(
        "subject",
        "Guest name: Jane Doe\nArrival: 2026-01-01\nDeparture: 2026-01-02\n",
        "text/plain",
    )
    assert result.room_lines == []


def test_room_line_missing_room_type_group_is_skipped():
    # A pattern whose room_type group can match empty/None for some
    # occurrences shouldn't produce a bogus RoomLineDTO.
    mapping = _mapping_with_room_lines(
        r"^Type:\s*(?P<room_type>.*)$", [_guest_name_field(), _checkin_field(), _checkout_field()]
    )
    parser = GenericFieldMappingParser(mapping)

    body = "Guest name: Jane Doe\nArrival: 2026-01-01\nDeparture: 2026-01-02\nType: \n"
    result = parser.parse("subject", body, "text/plain")
    assert result.room_lines == []


def test_room_line_nights_auto_computed_from_checkin_checkout_when_pattern_has_no_nights_group():
    # ROOM_LINE_PATTERN (the real Booking.com pattern) has no
    # (?P<nights>...) group at all — nights should still land on the
    # room line, computed from the reservation's own Arrival/Departure.
    mapping = _mapping_with_room_lines(
        ROOM_LINE_PATTERN, [_guest_name_field(), _checkin_field(), _checkout_field()]
    )
    parser = GenericFieldMappingParser(mapping)

    result = parser.parse("Fwd: New reservation via Booking.com", REAL_SINGLE_ROOM_BODY, "text/plain")

    assert result.checkin.isoformat() == "2026-07-21"
    assert result.checkout.isoformat() == "2026-07-22"
    assert result.room_lines[0].nights == 1


def test_every_room_line_gets_same_auto_computed_nights_for_multi_room_booking():
    mapping = _mapping_with_room_lines(
        ROOM_LINE_PATTERN, [_guest_name_field(), _checkin_field(), _checkout_field()]
    )
    mapping.fields[0].pattern = r"^Guest name:\s*(.+)$"
    parser = GenericFieldMappingParser(mapping)

    body_with_guest_name = TWO_ROOM_BODY + "Guest name: jane doe\n"
    result = parser.parse("New reservation via Booking.com", body_with_guest_name, "text/plain")

    assert result.checkin.isoformat() == "2026-08-01"
    assert result.checkout.isoformat() == "2026-08-03"
    assert result.room_lines[0].nights == 2
    assert result.room_lines[1].nights == 2


def test_explicit_nights_group_overrides_the_auto_computed_default():
    pattern = (
        r"^Type:\s*(?P<room_type>.+)$\n(?:.*\n)*?^Nights:\s*(?P<nights>\d+)$\n"
        r"(?:.*\n)*?^Guest:.*?Price:\s*(?P<price_total>[\d.]+)"
    )
    mapping = _mapping_with_room_lines(pattern, [_guest_name_field(), _checkin_field(), _checkout_field()])
    parser = GenericFieldMappingParser(mapping)

    body = (
        "Guest name: Jane Doe\n"
        "Arrival: 2026-08-01\n"
        "Departure: 2026-08-05\n"
        "Type: Split-stay Suite\n"
        "Nights: 1\n"
        "Guest: jane doePrice: 90.00\n"
    )
    result = parser.parse("subject", body, "text/plain")

    assert result.room_lines[0].nights == 1
