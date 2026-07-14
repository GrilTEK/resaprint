import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class ExtractionType(str, enum.Enum):
    regex = "regex"
    xpath = "xpath"


class FieldTransform(str, enum.Enum):
    none = "none"
    strip = "strip"
    parse_date_iso = "parse_date_iso"
    parse_date_eu = "parse_date_eu"
    parse_decimal = "parse_decimal"
    upper = "upper"
    lower = "lower"


class ParserFieldMapping(Base):
    __tablename__ = "parser_field_mappings"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    match_subject_regex: Mapped[str | None] = mapped_column(String(500), nullable=True)

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
