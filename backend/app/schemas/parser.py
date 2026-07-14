from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel

PARSED_RESERVATION_FIELDS = frozenset(
    {
        "external_ref",
        "source_channel",
        "guest_name",
        "guest_email",
        "guest_phone",
        "checkin",
        "checkout",
        "room_type",
        "guests_adults",
        "guests_children",
        "price_total",
        "price_currency",
    }
)


class ParsedReservation(BaseModel):
    external_ref: str | None = None
    source_channel: str
    guest_name: str
    guest_email: str | None = None
    guest_phone: str | None = None
    checkin: date
    checkout: date
    room_type: str | None = None
    guests_adults: int = 1
    guests_children: int = 0
    price_total: Decimal | None = None
    price_currency: str = "EUR"
    extra_fields: dict[str, Any] = {}
