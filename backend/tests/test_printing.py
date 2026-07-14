from datetime import date
from decimal import Decimal

from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation
from app.models.reservation_room_line import ReservationRoomLine
from app.services.printing import build_reservation_receipt


def _station() -> PrintStation:
    return PrintStation(
        name="Test",
        connection_type=StationConnectionType.lan_escpos,
        lan_host="192.0.2.1",
        lan_port=9100,
        paper_width_cols=42,
        codepage="cp437",
    )


def test_receipt_includes_avg_per_night_for_single_room_summary():
    reservation = Reservation(
        guest_name="Jane Doe",
        source_channel="manual",
        checkin=date(2026, 8, 1),
        checkout=date(2026, 8, 3),
        room_type="Double",
        price_total=Decimal("200.00"),
        price_currency="EUR",
    )
    reservation.room_lines = []

    text_summary, escpos_bytes = build_reservation_receipt(reservation, _station())

    assert "Avg/night: EUR 100.00" in text_summary
    assert b"Avg/night" in escpos_bytes
    assert len(escpos_bytes) > 0


def test_receipt_lists_every_room_line_not_just_first():
    reservation = Reservation(
        guest_name="Jane Doe",
        source_channel="manual",
        checkin=date(2026, 8, 1),
        checkout=date(2026, 8, 3),
        price_total=Decimal("470.50"),
        price_currency="EUR",
    )
    reservation.room_lines = [
        ReservationRoomLine(sort_order=0, room_type="Economy Double", price_total=Decimal("150.00")),
        ReservationRoomLine(sort_order=1, room_type="Deluxe Suite", price_total=Decimal("320.50")),
    ]

    text_summary, _ = build_reservation_receipt(reservation, _station())

    assert "Economy Double" in text_summary
    assert "Deluxe Suite" in text_summary
    assert "Total: EUR 470.50" in text_summary


def test_receipt_falls_back_to_single_room_type_when_no_room_lines():
    reservation = Reservation(
        guest_name="Jane Doe",
        source_channel="manual",
        checkin=date(2026, 8, 1),
        checkout=date(2026, 8, 2),
        room_type="Standard Single",
        price_total=Decimal("80.00"),
        price_currency="EUR",
    )
    reservation.room_lines = []

    text_summary, _ = build_reservation_receipt(reservation, _station())

    assert "Room: Standard Single" in text_summary
