from pydantic import BaseModel


class ConfigOut(BaseModel):
    imap_host: str | None
    imap_port: int
    imap_user: str | None
    imap_has_password: bool  # never expose the decrypted password over the API
    imap_folder: str
    imap_processed_folder: str
    imap_poll_seconds: int
    auto_print_enabled: bool
    auto_print_station_id: int | None
    room_auto_assign_enabled: bool
    receipt_font: str
    receipt_font_size: str
    receipt_bold_labels: bool
    receipt_show_nights: bool
    receipt_show_guests: bool
    receipt_show_channel: bool


def config_out_from_row(row) -> "ConfigOut":
    """Shared by routers/config.py (JSON API) and routers/admin_ui.py
    (Settings page) so the two don't drift out of sync as fields get
    added."""
    return ConfigOut(
        imap_host=row.imap_host,
        imap_port=row.imap_port,
        imap_user=row.imap_user,
        imap_has_password=bool(row.imap_password_encrypted),
        imap_folder=row.imap_folder,
        imap_processed_folder=row.imap_processed_folder,
        imap_poll_seconds=row.imap_poll_seconds,
        auto_print_enabled=row.auto_print_enabled,
        auto_print_station_id=row.auto_print_station_id,
        room_auto_assign_enabled=row.room_auto_assign_enabled,
        receipt_font=row.receipt_font,
        receipt_font_size=row.receipt_font_size,
        receipt_bold_labels=row.receipt_bold_labels,
        receipt_show_nights=row.receipt_show_nights,
        receipt_show_guests=row.receipt_show_guests,
        receipt_show_channel=row.receipt_show_channel,
    )


class ConfigUpdate(BaseModel):
    imap_host: str | None = None
    imap_port: int | None = None
    imap_user: str | None = None
    imap_password: str | None = None  # write-only; omit or blank = leave unchanged
    imap_folder: str | None = None
    imap_processed_folder: str | None = None
    imap_poll_seconds: int | None = None
    auto_print_enabled: bool | None = None
    auto_print_station_id: int | None = None
    room_auto_assign_enabled: bool | None = None
    receipt_font: str | None = None
    receipt_font_size: str | None = None
    receipt_bold_labels: bool | None = None
    receipt_show_nights: bool | None = None
    receipt_show_guests: bool | None = None
    receipt_show_channel: bool | None = None
