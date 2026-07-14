"""Pluggable reservation-email parsing.

`ReservationParser` is the interface every parser (reference or
DB-driven generic) implements. The registry tries parsers in order and
uses the first one whose `can_parse` returns True. This is the
deterministic, admin-configurable replacement for hardcoding a single
hotel/channel's email format.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.models.parser_mapping import ExtractionType, FieldTransform, ParserFieldMapping
from app.schemas.parser import PARSED_RESERVATION_FIELDS, ParsedReservation


class ParserError(ValueError):
    """Raised when a matched parser fails to extract a required field."""


class ReservationParser(Protocol):
    slug: str

    def can_parse(self, raw_subject: str, raw_body: str, content_type: str) -> bool: ...

    def parse(self, raw_subject: str, raw_body: str, content_type: str) -> ParsedReservation: ...


def _apply_transform(value: str, transform: FieldTransform) -> str | date | Decimal:
    if transform == FieldTransform.none:
        return value
    if transform == FieldTransform.strip:
        return value.strip()
    if transform == FieldTransform.upper:
        return value.upper()
    if transform == FieldTransform.lower:
        return value.lower()
    if transform == FieldTransform.parse_date_iso:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    if transform == FieldTransform.parse_date_eu:
        return datetime.strptime(value.strip(), "%d-%m-%Y").date()
    if transform == FieldTransform.parse_decimal:
        cleaned = value.strip().replace(",", "").replace(" ", "")
        try:
            return Decimal(cleaned)
        except InvalidOperation as exc:
            raise ParserError(f"could not parse decimal from {value!r}") from exc
    raise ParserError(f"unknown transform: {transform}")


class GenericFieldMappingParser:
    """A parser fully driven by a DB-backed `ParserFieldMapping` profile.

    Extraction is regex (against plain text) or xpath (against an HTML
    body via lxml). No eval() of any kind — the transform set is a
    small fixed enum.
    """

    def __init__(self, mapping: ParserFieldMapping) -> None:
        self.slug = mapping.profile_slug
        self._mapping = mapping

    def can_parse(self, raw_subject: str, raw_body: str, content_type: str) -> bool:
        pattern = self._mapping.match_subject_regex
        if not pattern:
            return True
        return re.search(pattern, raw_subject) is not None

    def parse(self, raw_subject: str, raw_body: str, content_type: str) -> ParsedReservation:
        values: dict[str, object] = {}
        for field in self._mapping.fields:
            if field.target_field not in PARSED_RESERVATION_FIELDS:
                raise ParserError(f"unmapped target field: {field.target_field}")

            raw_value = self._extract(field, raw_body, content_type)
            if raw_value is None:
                if field.is_required:
                    raise ParserError(f"required field {field.target_field!r} not found")
                continue

            values[field.target_field] = _apply_transform(raw_value, field.transform)

        values.setdefault("source_channel", self._mapping.profile_slug)
        return ParsedReservation.model_validate(values)

    def _extract(self, field, raw_body: str, content_type: str) -> str | None:
        if field.extraction_type == ExtractionType.regex:
            match = re.search(field.pattern, raw_body, re.MULTILINE)
            if not match:
                return None
            return match.group(field.group_index)

        if field.extraction_type == ExtractionType.xpath:
            from lxml import etree

            tree = etree.HTML(raw_body)
            if tree is None:
                return None
            results = tree.xpath(field.pattern)
            if not results:
                return None
            first = results[0]
            return str(first).strip() if not hasattr(first, "text") else (first.text or "").strip()

        raise ParserError(f"unknown extraction type: {field.extraction_type}")


class ParserRegistry:
    def __init__(self, parsers: list[ReservationParser] | None = None) -> None:
        self._parsers: list[ReservationParser] = list(parsers or [])

    def register(self, parser: ReservationParser) -> None:
        self._parsers.append(parser)

    def find(self, raw_subject: str, raw_body: str, content_type: str) -> ReservationParser | None:
        for parser in self._parsers:
            if parser.can_parse(raw_subject, raw_body, content_type):
                return parser
        return None
