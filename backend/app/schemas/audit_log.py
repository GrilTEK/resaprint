from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    actor: str
    action: str
    entity_type: str | None
    entity_id: int | None
    detail: dict[str, Any] | None
    created_at: datetime
