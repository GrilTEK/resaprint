import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, LargeBinary, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class PrintJobStatus(str, enum.Enum):
    queued = "queued"
    sent = "sent"
    printed = "printed"
    failed = "failed"
    cancelled = "cancelled"


class PrintJob(Base):
    __tablename__ = "print_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    reservation_id: Mapped[int | None] = mapped_column(
        ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True
    )
    station_id: Mapped[int] = mapped_column(
        ForeignKey("print_stations.id", ondelete="CASCADE"), nullable=False
    )

    status: Mapped[PrintJobStatus] = mapped_column(
        Enum(PrintJobStatus, name="print_job_status"), default=PrintJobStatus.queued
    )

    payload_text: Mapped[str] = mapped_column(Text, nullable=False)
    escpos_bytes: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    printed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    reservation: Mapped["Reservation | None"] = relationship(back_populates="print_jobs")  # noqa: F821
    station: Mapped["PrintStation"] = relationship(back_populates="print_jobs")  # noqa: F821
