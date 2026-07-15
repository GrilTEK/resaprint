from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.print_station import PrintStation


class AppSettings(Base):
    """Singleton row (id is always 1) holding runtime-editable config —
    IMAP ingestion settings and the auto-print default station,
    editable from the admin UI instead of requiring a container
    restart with a new .env."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)

    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    imap_folder: Mapped[str] = mapped_column(String(255), default="INBOX")
    imap_processed_folder: Mapped[str] = mapped_column(String(255), default="Processed")
    imap_poll_seconds: Mapped[int] = mapped_column(Integer, default=60)

    # If enabled, a newly-ingested (successfully parsed) reservation is
    # printed automatically to this station — no manual "Print now"
    # needed. SET NULL (not CASCADE) if the station is deleted, so
    # losing a station just quietly disables auto-print rather than
    # touching this row's other settings.
    auto_print_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    auto_print_station_id: Mapped[int | None] = mapped_column(
        ForeignKey("print_stations.id", ondelete="SET NULL"), nullable=True
    )

    # Receipt layout — applied to every printed receipt (LAN + USB
    # agent alike), global rather than per-station for simplicity.
    receipt_font: Mapped[str] = mapped_column(String(10), default="font_a")  # "font_a" | "font_b"
    receipt_font_size: Mapped[str] = mapped_column(String(10), default="normal")  # "normal" | "large"
    receipt_bold_labels: Mapped[bool] = mapped_column(Boolean, default=False)
    receipt_show_nights: Mapped[bool] = mapped_column(Boolean, default=True)
    receipt_show_guests: Mapped[bool] = mapped_column(Boolean, default=True)
    receipt_show_channel: Mapped[bool] = mapped_column(Boolean, default=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    auto_print_station: Mapped["PrintStation | None"] = relationship()
