from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.round import RoundStatus


class TandaRoundBase(BaseModel):
    round_number: int
    slot_number_beneficiary: int
    due_date: datetime
    expected_amount: float


class TandaRoundResponse(TandaRoundBase):
    id: UUID
    tanda_id: UUID
    collected_amount: float
    status: RoundStatus
    closed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)
