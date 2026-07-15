from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.models.reservation import ReservationStatus


class ReservationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    external_ref: str | None
    source_channel: str
    parser_slug: str | None
    guest_name: str
    guest_email: str | None
    guest_phone: str | None
    checkin: date
    checkout: date
    room_type: str | None
    guests_adults: int
    guests_children: int
    price_total: Decimal | None
    price_currency: str
    status: ReservationStatus
    extra_fields: dict[str, Any] | None
    assigned_room_id: int | None
    created_at: datetime
    updated_at: datetime


class ReservationCreate(BaseModel):
    external_ref: str | None = None
    source_channel: str = "manual"
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


class ReservationUpdate(BaseModel):
    guest_name: str | None = None
    guest_email: str | None = None
    guest_phone: str | None = None
    checkin: date | None = None
    checkout: date | None = None
    room_type: str | None = None
    guests_adults: int | None = None
    guests_children: int | None = None
    price_total: Decimal | None = None
    price_currency: str | None = None
    status: ReservationStatus | None = None


class PrintRequest(BaseModel):
    station_id: int
