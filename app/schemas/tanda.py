from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.tanda import FrequencyType, AssignmentMethod, TandaStatus
from app.schemas.user import UserResponse
from app.schemas.slot import TandaSlotResponse
from app.schemas.round import TandaRoundResponse


class TandaBase(BaseModel):
    title: str
    description: Optional[str] = None
    contribution_amount: float
    total_slots: int
    frequency: FrequencyType = FrequencyType.QUINCENAL
    assignment_method: AssignmentMethod = AssignmentMethod.DRAW
    grace_period_days: int = 2
    late_fee_per_day: float = 0.0
    require_proof_photo: bool = True
    start_date: Optional[datetime] = None


class TandaCreate(TandaBase):
    pass


class TandaUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    grace_period_days: Optional[int] = None
    late_fee_per_day: Optional[float] = None
    start_date: Optional[datetime] = None


class TandaResponse(TandaBase):
    id: UUID
    organizer_id: UUID
    currency: str
    payout_total: float
    status: TandaStatus
    invite_code: str
    created_at: datetime
    organizer: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)


class TandaDetailResponse(TandaResponse):
    slots: List[TandaSlotResponse] = []
    rounds: List[TandaRoundResponse] = []
