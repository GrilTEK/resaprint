from pydantic import BaseModel, ConfigDict

from app.models.parser_mapping import ExtractionType, FieldTransform


class ParserFieldMappingFieldOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    target_field: str
    extraction_type: ExtractionType
    pattern: str
    group_index: int
    transform: FieldTransform
    is_required: bool


class ParserFieldMappingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    profile_slug: str
    is_active: bool
    match_subject_regex: str | None
    fields: list[ParserFieldMappingFieldOut] = []


class ParserFieldMappingCreate(BaseModel):
    profile_slug: str
    match_subject_regex: str | None = None
    is_active: bool = True


class ParserFieldCreate(BaseModel):
    label: str
    target_field: str
    extraction_type: ExtractionType
    pattern: str
    group_index: int = 1
    transform: FieldTransform = FieldTransform.none
    is_required: bool = True


class ParserTestRequest(BaseModel):
    subject: str = ""
    body: str
    content_type: str = "text/plain"


class ParserTestResult(BaseModel):
    matched: bool
    parsed: dict | None = None
    error: str | None = None
