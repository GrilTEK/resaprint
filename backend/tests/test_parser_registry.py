from datetime import date
from decimal import Decimal

import pytest

from app.models.parser_mapping import (
    ExtractionType,
    FieldTransform,
    ParserFieldMapping,
    ParserFieldMappingField,
)
from app.services.parser_registry import GenericFieldMappingParser, ParserError, ParserRegistry
from app.services.parsers.reference_booking_com import ReferenceBookingComParser


def _mapping_field(**kwargs) -> ParserFieldMappingField:
    defaults = dict(
        label="field",
        extraction_type=ExtractionType.regex,
        group_index=1,
        transform=FieldTransform.none,
        is_required=True,
    )
    defaults.update(kwargs)
    return ParserFieldMappingField(**defaults)


def _mapping(profile_slug="generic_profile", match_subject_regex=None, fields=None) -> ParserFieldMapping:
    mapping = ParserFieldMapping(
        profile_slug=profile_slug,
        is_active=True,
        match_subject_regex=match_subject_regex,
    )
    mapping.fields = fields or []
    return mapping


SAMPLE_BODY = """\
Guest: John Smith
Arrival: 2026-09-01
Departure: 2026-09-05
Amount: 450.50
"""


def _generic_reservation_mapping() -> ParserFieldMapping:
    return _mapping(
        profile_slug="generic_channel_x",
        match_subject_regex=r"Reservation notice",
        fields=[
            _mapping_field(target_field="guest_name", pattern=r"^Guest:\s*(.+)$"),
            _mapping_field(
                target_field="checkin",
                pattern=r"^Arrival:\s*(.+)$",
                transform=FieldTransform.parse_date_iso,
            ),
            _mapping_field(
                target_field="checkout",
                pattern=r"^Departure:\s*(.+)$",
                transform=FieldTransform.parse_date_iso,
            ),
            _mapping_field(
                target_field="price_total",
                pattern=r"^Amount:\s*(.+)$",
                transform=FieldTransform.parse_decimal,
                is_required=False,
            ),
        ],
    )


def test_generic_parser_can_parse_uses_subject_regex():
    parser = GenericFieldMappingParser(_generic_reservation_mapping())
    assert parser.can_parse("Reservation notice #123", SAMPLE_BODY, "text/plain")
    assert not parser.can_parse("Unrelated subject", SAMPLE_BODY, "text/plain")


def test_generic_parser_null_subject_regex_always_matches():
    parser = GenericFieldMappingParser(_mapping(match_subject_regex=None, fields=[]))
    assert parser.can_parse("literally anything", SAMPLE_BODY, "text/plain")


def test_generic_parser_extracts_and_transforms_fields():
    parser = GenericFieldMappingParser(_generic_reservation_mapping())
    result = parser.parse("Reservation notice #123", SAMPLE_BODY, "text/plain")

    assert result.guest_name == "John Smith"
    assert result.checkin == date(2026, 9, 1)
    assert result.checkout == date(2026, 9, 5)
    assert result.price_total == Decimal("450.50")
    assert result.source_channel == "generic_channel_x"


def test_generic_parser_raises_on_missing_required_field():
    mapping = _mapping(
        fields=[_mapping_field(target_field="guest_name", pattern=r"^Nonexistent:\s*(.+)$", is_required=True)]
    )
    parser = GenericFieldMappingParser(mapping)
    with pytest.raises(ParserError):
        parser.parse("subject", SAMPLE_BODY, "text/plain")


def test_generic_parser_rejects_unmapped_target_field():
    mapping = _mapping(
        fields=[_mapping_field(target_field="not_a_real_field", pattern=r"^Guest:\s*(.+)$")]
    )
    parser = GenericFieldMappingParser(mapping)
    with pytest.raises(ParserError):
        parser.parse("subject", SAMPLE_BODY, "text/plain")


def test_registry_returns_first_matching_parser_in_order():
    reference = ReferenceBookingComParser()
    generic = GenericFieldMappingParser(_generic_reservation_mapping())
    registry = ParserRegistry([reference, generic])

    match = registry.find("Reservation notice #123", SAMPLE_BODY, "text/plain")
    assert match is generic

    match2 = registry.find(
        "New booking confirmation - Booking.com",
        "Guest name: X\nCheck-in: 01-01-2026\nCheck-out: 02-01-2026\n",
        "text/plain",
    )
    assert match2 is reference


def test_registry_returns_none_when_no_parser_matches():
    registry = ParserRegistry([ReferenceBookingComParser()])
    assert registry.find("totally unrelated", SAMPLE_BODY, "text/plain") is None
