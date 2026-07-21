from datetime import date
from decimal import Decimal

from app.models.app_settings import AppSettings
from app.models.print_station import PrintStation, StationConnectionType
from app.models.reservation import Reservation, ReservationStatus
from app.models.reservation_room_line import ReservationRoomLine
from app.models.room import Room
from app.services.escpos_builder import bold
from app.services.printing import build_reservation_receipt


def _station(paper_width_cols: int = 42) -> PrintStation:
    return PrintStation(
        name="Test",
        connection_type=StationConnectionType.lan_escpos,
        lan_host="192.0.2.1",
        lan_port=9100,
        paper_width_cols=paper_width_cols,
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


def test_receipt_header_uses_source_channel():
    text_summary, _ = build_reservation_receipt(_reservation(), _station())

    assert text_summary.startswith("BOOKING_COM_CUBILIS REZERVACIJA\n")


def test_receipt_shows_total_as_skupaj():
    text_summary, _ = build_reservation_receipt(_reservation(), _station())

    assert "SKUPAJ: EUR 200.00" in text_summary


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

    assert "Sobe:" in text_summary
    assert "Economy Double" in text_summary
    assert "Deluxe Suite" in text_summary
    assert "SKUPAJ: EUR 470.50" in text_summary


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

    assert "Sobe:" in text_summary
    assert "Standard Single" in text_summary


def test_receipt_shows_assigned_room_number():
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
    reservation.assigned_room = Room(room_number="101", category="Standard Single")

    text_summary, _ = build_reservation_receipt(reservation, _station())

    assert "Standard Single (Soba 101)" in text_summary


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


def test_receipt_shows_nights_and_guests_combined_by_default():
    text_summary, _ = build_reservation_receipt(_reservation(), _station())

    assert "GOSTI: 3  |  NOČI: 2" in text_summary


def test_receipt_hides_nights_guests_channel_when_disabled_in_settings():
    app_settings = _app_settings(receipt_show_nights=False, receipt_show_guests=False, receipt_show_channel=False)

    text_summary, _ = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert "GOSTI:" not in text_summary
    assert "NOČI:" not in text_summary
    assert text_summary.startswith("REZERVACIJA\n")
    assert "BOOKING_COM_CUBILIS" not in text_summary


def test_receipt_shows_only_nights_when_guests_disabled():
    app_settings = _app_settings(receipt_show_guests=False)

    text_summary, _ = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert "NOČI: 2" in text_summary
    assert "GOSTI:" not in text_summary


def test_receipt_applies_bold_labels_setting():
    app_settings = _app_settings(receipt_bold_labels=True)

    _, escpos_bytes = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert bold(True) in escpos_bytes


def test_receipt_applies_large_font_size_setting():
    from app.services.escpos_builder import text_size

    app_settings = _app_settings(receipt_font_size="large")

    _, escpos_bytes = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert text_size(2, 2) in escpos_bytes


def test_receipt_applies_xlarge_font_size_setting():
    from app.services.escpos_builder import text_size

    app_settings = _app_settings(receipt_font_size="xlarge")

    _, escpos_bytes = build_reservation_receipt(_reservation(), _station(), app_settings)

    assert text_size(3, 3) in escpos_bytes


def test_receipt_includes_avg_per_night():
    text_summary, _ = build_reservation_receipt(_reservation(), _station())

    assert "Povp./noč: EUR 100.00" in text_summary


def test_receipt_shows_reservation_number_or_dash():
    text_summary, _ = build_reservation_receipt(_reservation(external_ref="12345"), _station())
    assert "Reservation nr.: 12345" in text_summary

    text_summary_no_ref, _ = build_reservation_receipt(_reservation(external_ref=None), _station())
    assert "Reservation nr.: -" in text_summary_no_ref


def test_receipt_marks_cancelled_reservation_prominently():
    """A cancelled reservation must be unmistakable on the printed
    paper, not just in the admin UI — the header, a large bold banner
    (top and bottom), and the plain-text payload all call it out."""
    from app.services.escpos_builder import text_size

    reservation = _reservation(status=ReservationStatus.cancelled)
    text_summary, escpos_bytes = build_reservation_receipt(reservation, _station())

    assert "PREKLICANO" in text_summary.splitlines()[0]
    assert text_summary.count("*** PREKLICANO ***") == 2
    assert text_size(3, 3) in escpos_bytes


def test_receipt_does_not_mark_active_reservation_as_cancelled():
    text_summary, _ = build_reservation_receipt(_reservation(status=ReservationStatus.confirmed), _station())

    assert "PREKLICANO" not in text_summary


def test_receipt_wraps_long_room_names_on_narrow_paper():
    reservation = _reservation(room_type="A Very Long Room Category Name Indeed")
    reservation.room_lines = []

    text_summary, _ = build_reservation_receipt(reservation, _station(paper_width_cols=20))

    assert "  Category Name Indeed" in text_summary
