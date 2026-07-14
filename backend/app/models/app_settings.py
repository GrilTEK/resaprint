from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AppSettings(Base):
    """Singleton row (id is always 1) holding runtime-editable config —
    currently just IMAP ingestion settings, editable from the admin UI
    instead of requiring a container restart with a new .env."""

    __tablename__ = "app_settings"

    id: Mapped[int] = mapped_column(primary_key=True)

    imap_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_port: Mapped[int] = mapped_column(Integer, default=993)
    imap_user: Mapped[str | None] = mapped_column(String(255), nullable=True)
    imap_password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    imap_folder: Mapped[str] = mapped_column(String(255), default="INBOX")
    imap_processed_folder: Mapped[str] = mapped_column(String(255), default="Processed")
    imap_poll_seconds: Mapped[int] = mapped_column(Integer, default=60)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
