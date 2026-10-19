from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict


class UserBase(BaseModel):
    phone: str
    email: Optional[EmailStr] = None
    full_name: str
    clabe: Optional[str] = None
    bank_name: Optional[str] = None
    avatar_url: Optional[str] = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    clabe: Optional[str] = None
    bank_name: Optional[str] = None
    avatar_url: Optional[str] = None
    fcm_token: Optional[str] = None


class UserResponse(UserBase):
    id: UUID
    tanda_score: int
    tandas_completed: int
    on_time_payments: int
    late_payments: int
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
