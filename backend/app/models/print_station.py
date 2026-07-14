import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class StationConnectionType(str, enum.Enum):
    lan_escpos = "lan_escpos"
    usb_agent = "usb_agent"


class PrintStation(Base):
    __tablename__ = "print_stations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    connection_type: Mapped[StationConnectionType] = mapped_column(
        Enum(StationConnectionType, name="station_connection_type"), nullable=False
    )

    lan_host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lan_port: Mapped[int] = mapped_column(Integer, default=9100)
    paper_width_cols: Mapped[int] = mapped_column(Integer, default=42)
    codepage: Mapped[str] = mapped_column(String(20), default="cp437")

    api_key_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    api_key_prefix: Mapped[str | None] = mapped_column(String(12), nullable=True)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # cascade="all, delete-orphan" so deleting a station has SQLAlchemy
    # actually DELETE its print_jobs rather than trying to null out
    # station_id first (which would violate its NOT NULL constraint —
    # station_id has no SET NULL fallback the way reservation_id does).
    print_jobs: Mapped[list["PrintJob"]] = relationship(  # noqa: F821
        back_populates="station", cascade="all, delete-orphan"
    )
