from pydantic import BaseModel


class LoginRequest(BaseModel):
    pin: str


class LoginResponse(BaseModel):
    label: str
