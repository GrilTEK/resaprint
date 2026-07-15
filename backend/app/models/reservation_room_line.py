from decimal import Decimal

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ReservationRoomLine(Base):
    """One room/rate line within a reservation. Most bookings have
    exactly one; multi-room bookings (a single reservation covering
    several room types/rates) get one row per room here instead of
    collapsing into a single Reservation.room_type string."""

    __tablename__ = "reservation_room_lines"

    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int] = mapped_column(
        ForeignKey("reservations.id", ondelete="CASCADE"), nullable=False
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    room_type: Mapped[str] = mapped_column(String(200))
    nights: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_per_night: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    price_total: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)

    assigned_room_id: Mapped[int | None] = mapped_column(
        ForeignKey("rooms.id", ondelete="SET NULL"), nullable=True
    )

    reservation: Mapped["Reservation"] = relationship(back_populates="room_lines")  # noqa: F821
    assigned_room: Mapped["Room | None"] = relationship(foreign_keys=[assigned_room_id])  # noqa: F821
