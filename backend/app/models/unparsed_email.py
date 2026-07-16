import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UnparsedEmailStatus(str, enum.Enum):
    pending = "pending"
    resolved = "resolved"
    ignored = "ignored"


class UnparsedEmail(Base):
    """A reservation email that no parser could handle — either no
    parser's `can_parse` matched, or a matched parser raised
    ParserError. Unlike the audit log (which only records the
    subject), the full raw subject/body are kept here so an operator
    can fix or add a parser mapping and reparse this exact email from
    the admin UI, instead of needing the sender to resend it."""

    __tablename__ = "unparsed_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(50), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    parser_slug: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[UnparsedEmailStatus] = mapped_column(
        Enum(UnparsedEmailStatus, name="unparsed_email_status"),
        default=UnparsedEmailStatus.pending,
        nullable=False,
    )
    resolved_reservation_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("reservations.id", ondelete="SET NULL"), nullable=True
    )
    resolved_reservation = relationship("Reservation")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
