from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.print_job import PrintJobStatus


class PrintJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reservation_id: int | None
    station_id: int
    status: PrintJobStatus
    payload_text: str
    attempts: int
    last_error: str | None
    requested_by: str | None
    created_at: datetime
    sent_at: datetime | None
    printed_at: datetime | None


class ManualPrintJobCreate(BaseModel):
    station_id: int
    payload_text: str


class AckRequest(BaseModel):
    status: PrintJobStatus
    error: str | None = None
