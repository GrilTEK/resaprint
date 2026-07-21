import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ExtractionType(str, enum.Enum):
    regex = "regex"
    xpath = "xpath"


class ParserMappingKind(str, enum.Enum):
    reservation = "reservation"  # creates a new Reservation from the parsed fields
    cancellation = "cancellation"  # looks up an existing Reservation by external_ref and marks it cancelled


class FieldTransform(str, enum.Enum):
    none = "none"
    strip = "strip"
    parse_date_iso = "parse_date_iso"
    parse_date_eu = "parse_date_eu"
    parse_date_long = "parse_date_long"  # "Friday, July 31, 2026" (Cubilis HTML confirmation emails)
    parse_decimal = "parse_decimal"
    upper = "upper"
    lower = "lower"


class ParserFieldMapping(Base):
    __tablename__ = "parser_field_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_subject_regex: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # "reservation" (default): a match creates a new Reservation.
    # "cancellation": a match looks up the existing Reservation by the
    # mapped external_ref field and marks it cancelled instead — for
    # OTA "booking cancelled" notices, which reuse a similar template
    # to the original confirmation email but must not become a
    # duplicate new booking.
    kind: Mapped[ParserMappingKind] = mapped_column(
        Enum(ParserMappingKind, name="parser_mapping_kind"), default=ParserMappingKind.reservation
    )

    # Optional: a single regex with named groups (?P<room_type>...),
    # (?P<price_total>...), (?P<price_per_night>...), (?P<nights>...) —
    # applied with re.finditer (not re.search) so a reservation email
    # covering multiple room types/rates produces one ReservationRoomLine
    # per match instead of only the first one being captured.
    room_line_pattern: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    fields: Mapped[list["ParserFieldMappingField"]] = relationship(
        back_populates="mapping", cascade="all, delete-orphan", order_by="ParserFieldMappingField.id"
    )


class ParserFieldMappingField(Base):
    __tablename__ = "parser_field_mapping_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    mapping_id: Mapped[int] = mapped_column(
        ForeignKey("parser_field_mappings.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    target_field: Mapped[str] = mapped_column(String(100), nullable=False)
    extraction_type: Mapped[ExtractionType] = mapped_column(
        Enum(ExtractionType, name="extraction_type"), nullable=False
    )
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    group_index: Mapped[int] = mapped_column(Integer, default=1)
    transform: Mapped[FieldTransform] = mapped_column(
        Enum(FieldTransform, name="field_transform"), default=FieldTransform.none
    )
    is_required: Mapped[bool] = mapped_column(Boolean, default=True)

    mapping: Mapped["ParserFieldMapping"] = relationship(back_populates="fields")
