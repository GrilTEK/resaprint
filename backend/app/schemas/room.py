from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_number: str
    category: str
    floor: str | None
    notes: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime


class RoomCreate(BaseModel):
    room_number: str
    category: str
    floor: str | None = None
    notes: str | None = None


class RoomUpdate(BaseModel):
    room_number: str | None = None
    category: str | None = None
    floor: str | None = None
    notes: str | None = None
    is_active: bool | None = None
