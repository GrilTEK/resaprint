from datetime import date
from decimal import Decimal

from app.models.app_settings import AppSettings
from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation
from app.models.reservation_room_line import ReservationRoomLine
from app.services.escpos_builder import bold
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


def _reservation(**overrides) -> Reservation:
    defaults = dict(
        guest_name="Jane Doe",
        source_channel="booking_com_cubilis",
        checkin=date(2026, 8, 1),
        checkout=date(2026, 8, 3),
        room_type="Double",
        guests_adults=2,
        guests_children=1,
        price_total=Decimal("200.00"),
        price_currency="EUR",
    )
    defaults.update(overrides)
    reservation = Reservation(**defaults)
    reservation.room_lines = []
    return reservation


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


def _app_settings(**overrides) -> AppSettings:
    # AppSettings(**kwargs) doesn't apply SQLAlchemy column `default=`
    # values outside a session flush, so every field build_reservation_receipt
    # reads must be given explicitly here.
    defaults = dict(
        receipt_font="font_a",
        receipt_font_size="normal",
        receipt_bold_labels=False,
        receipt_show_nights=True,
        receipt_show_guests=True,
        receipt_show_channel=True,
    )
    defaults.update(overrides)
    return AppSettings(**defaults)


def test_receipt_shows_nights_guests_channel_by_default():
    text_summary, _ = build_reservation_receipt(_reservation(), _station())

    assert "Nights: 2" in text_summary
    assert "Guests: 2 adults, 1 child" in text_summary
    assert "Channel: booking_com_cubilis" in text_summary


def test_receipt_hides_nights_guests_channel_when_disabled_in_settings():
    app_settings = _app_settings(receipt_show_nights=False, receipt_show_guests=False, receipt_show_channel=False)

    text_summary, _ = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert "Nights:" not in text_summary
    assert "Guests:" not in text_summary
    assert "Channel:" not in text_summary


def test_receipt_applies_bold_labels_setting():
    app_settings = _app_settings(receipt_bold_labels=True)

    _, escpos_bytes = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert bold(True) in escpos_bytes


def test_receipt_applies_large_font_size_setting():
    from app.services.escpos_builder import text_size

    app_settings = _app_settings(receipt_font_size="large")

    _, escpos_bytes = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert text_size(2, 2) in escpos_bytes


def test_receipt_guests_label_singular_forms():
    text_summary, _ = build_reservation_receipt(
        _reservation(guests_adults=1, guests_children=0), _station()
    )
    assert "Guests: 1 adult" in text_summary
    assert "1 adults" not in text_summary
