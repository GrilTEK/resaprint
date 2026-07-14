import enum
from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Date, DateTime, Enum, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.print_job import PrintJob
    from app.models.reservation_room_line import ReservationRoomLine


class ReservationStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    cancelled = "cancelled"
    manual = "manual"


class Reservation(Base):
    __tablename__ = "reservations"

    id: Mapped[int] = mapped_column(primary_key=True)
    external_ref: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_channel: Mapped[str] = mapped_column(String(100), nullable=False)
    parser_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)

    guest_name: Mapped[str] = mapped_column(String(200), nullable=False)
    guest_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    guest_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)

    checkin: Mapped[date] = mapped_column(Date, nullable=False)
    checkout: Mapped[date] = mapped_column(Date, nullable=False)
    room_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    guests_adults: Mapped[int] = mapped_column(default=1)
    guests_children: Mapped[int] = mapped_column(default=0)

    price_total: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_currency: Mapped[str] = mapped_column(String(3), default="EUR")

    status: Mapped[ReservationStatus] = mapped_column(
        Enum(ReservationStatus, name="reservation_status"),
        default=ReservationStatus.pending,
    )

    raw_source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra_fields: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    print_jobs: Mapped[list["PrintJob"]] = relationship(back_populates="reservation")
    room_lines: Mapped[list["ReservationRoomLine"]] = relationship(
        back_populates="reservation",
        cascade="all, delete-orphan",
        order_by="ReservationRoomLine.sort_order",
    )
