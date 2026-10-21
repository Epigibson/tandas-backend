from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.slot import PayoutStatus
from app.schemas.user import UserResponse


class TandaSlotBase(BaseModel):
    slot_number: int
    scheduled_payout_date: Optional[datetime] = None


class TandaSlotCreate(TandaSlotBase):
    user_id: Optional[UUID] = None


class TandaSlotResponse(TandaSlotBase):
    id: UUID
    tanda_id: UUID
    user_id: Optional[UUID] = None
    payout_status: PayoutStatus
    payout_proof_url: Optional[str] = None
    payout_confirmed_at: Optional[datetime] = None
    user: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)


class SlotMoveRequest(BaseModel):
    slot_number: int
