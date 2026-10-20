from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, Field
from app.schemas.user import UserResponse


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class LoginRequest(BaseModel):
    phone_or_email: str
    password: str


class DeviceRegisterRequest(BaseModel):
    device_name: str = Field(default="Teléfono", max_length=100)


class DeviceRegisterResponse(BaseModel):
    device_id: UUID
    device_secret: str


class DeviceLoginRequest(BaseModel):
    device_id: UUID
    device_secret: str


class PasswordResetRequest(BaseModel):
    phone_or_email: str
    code: str
    new_password: str = Field(min_length=6)


class ResetCodeResponse(BaseModel):
    code: str
    expires_at: datetime
