"""Field-mapping config for a real Cubilis (Stardekk IBE) confirmation
email a user shared — plain-text-rendered blocks with blank-line
separators, English long-form dates ("Friday, July 31, 2026"), and a
"Rooms and extras" section mixing genuine room lines with add-ons
(tourist tax, garage) that must NOT be picked up as rooms."""
from decimal import Decimal

from app.models.parser_mapping import ExtractionType, FieldTransform, ParserFieldMapping, ParserFieldMappingField
from app.services.parser_registry import GenericFieldMappingParser

REAL_CUBILIS_BODY = """\
Reservation number: 90000002,

Made by Ana Novak on 15 July 2026 19:03.

Ana Novak

n/a n/a

n/a n/a

Arrival:

Friday, July 31, 2026

Departure:

Tuesday, August 4, 2026

Check in:

15:00

Rooms and extras

DOUBLE ROOM HIGH FLOOR WITH BRAKFAST, Non Refundable

Guestname: Mr. Ana Novak

Adults: 2.

€ 804.00

TOURIST TAX (per adult per night) 4n × 2p

€ 20.00

GARAGE (per car per night - 24h) 4n

€ 40.00

Total:

€ 864.00

Credit card

The reservation has been guaranteed by credit card.

Cubilis IBE by Stardekk &times
"""

ROOM_LINE_PATTERN = (
    r"^(?P<room_type>[A-Z][^\n]*)\n\s*\nGuestname:[^\n]*\n\s*\nAdults:\s*\d+\.\s*\n\s*\n"
    r"€\s*(?P<price_total>[\d.,]+)"
)


def _mapping() -> ParserFieldMapping:
    mapping = ParserFieldMapping(profile_slug="cubilis", is_active=True, room_line_pattern=ROOM_LINE_PATTERN)
    mapping.fields = [
        ParserFieldMappingField(
            label="External ref",
            target_field="external_ref",
            extraction_type=ExtractionType.regex,
            pattern=r"^Reservation number:\s*(\d+)",
            group_index=1,
            transform=FieldTransform.none,
            is_required=True,
        ),
        ParserFieldMappingField(
            label="Guest name",
            target_field="guest_name",
            extraction_type=ExtractionType.regex,
            pattern=r"^Made by\s+(.+?)\s+on\s",
            group_index=1,
            transform=FieldTransform.none,
            is_required=True,
        ),
        ParserFieldMappingField(
            label="Arrival",
            target_field="checkin",
            extraction_type=ExtractionType.regex,
            pattern=r"^Arrival:\s*\n\s*(.+)$",
            group_index=1,
            transform=FieldTransform.parse_date_long,
            is_required=True,
        ),
        ParserFieldMappingField(
            label="Departure",
            target_field="checkout",
            extraction_type=ExtractionType.regex,
            pattern=r"^Departure:\s*\n\s*(.+)$",
            group_index=1,
            transform=FieldTransform.parse_date_long,
            is_required=True,
        ),
        ParserFieldMappingField(
            label="Total",
            target_field="price_total",
            extraction_type=ExtractionType.regex,
            pattern=r"^Total:\s*\n\s*€\s*([\d.,]+)",
            group_index=1,
            transform=FieldTransform.parse_decimal,
            is_required=True,
        ),
        ParserFieldMappingField(
            label="Adults",
            target_field="guests_adults",
            extraction_type=ExtractionType.regex,
            pattern=r"^Adults:\s*(\d+)\.",
            group_index=1,
            transform=FieldTransform.none,
            is_required=False,
        ),
    ]
    return mapping


def test_scalar_fields_extracted_from_real_cubilis_email():
    parser = GenericFieldMappingParser(_mapping())

    result = parser.parse("Reservation confirmation", REAL_CUBILIS_BODY, "text/plain")

    assert result.external_ref == "90000002"
    assert result.guest_name == "Ana Novak"
    assert result.checkin.isoformat() == "2026-07-31"
    assert result.checkout.isoformat() == "2026-08-04"
    assert result.price_total == Decimal("864.00")
    assert result.guests_adults == 2


def test_room_line_extracted_without_picking_up_tourist_tax_or_garage():
    parser = GenericFieldMappingParser(_mapping())

    result = parser.parse("Reservation confirmation", REAL_CUBILIS_BODY, "text/plain")

    assert len(result.room_lines) == 1
    line = result.room_lines[0]
    assert line.room_type == "DOUBLE ROOM HIGH FLOOR WITH BRAKFAST, Non Refundable"
    assert line.price_total == Decimal("804.00")
    # nights auto-computed from checkin/checkout (no explicit
    # (?P<nights>...) group in ROOM_LINE_PATTERN): July 31 -> Aug 4.
    assert line.nights == 4
