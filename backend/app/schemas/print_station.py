from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.models.print_station import StationConnectionType


class PrintStationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    connection_type: StationConnectionType
    lan_host: str | None
    lan_port: int
    paper_width_cols: int
    codepage: str
    api_key_prefix: str | None
    paired_at: datetime | None
    is_active: bool
    last_seen_at: datetime | None
    created_at: datetime


class PrintStationCreate(BaseModel):
    name: str
    connection_type: StationConnectionType
    lan_host: str | None = None
    lan_port: int = 9100
    paper_width_cols: int = 42
    codepage: str = "cp437"


class PairResponse(BaseModel):
    station_id: int
    api_key: str
