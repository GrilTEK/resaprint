from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.admin_pin import AdminRole


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    label: str
    role: AdminRole
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime


class UserCreate(BaseModel):
    label: str
    pin: str
    role: AdminRole = AdminRole.reception


class UserUpdate(BaseModel):
    label: str | None = None
    role: AdminRole | None = None
    is_active: bool | None = None
    pin: str | None = None  # write-only; omit or blank = leave unchanged
