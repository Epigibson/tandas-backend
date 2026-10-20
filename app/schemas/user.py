from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, EmailStr, ConfigDict, Field


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


class AdminUserUpdate(BaseModel):
    """Lo que el admin puede corregir de un familiar. El teléfono es con lo que entra."""
    full_name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    phone: Optional[str] = Field(default=None, pattern=r"^\d{10}$")
    email: Optional[EmailStr] = None
    clabe: Optional[str] = Field(default=None, pattern=r"^\d{18}$")
    bank_name: Optional[str] = Field(default=None, max_length=100)


class UserResponse(UserBase):
    id: UUID
    tanda_score: int
    tandas_completed: int
    on_time_payments: int
    late_payments: int
    is_active: bool
    is_superuser: bool = False
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
