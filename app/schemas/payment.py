from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict
from app.models.payment import PaymentStatus
from app.schemas.user import UserResponse


class PaymentBase(BaseModel):
    amount: float
    late_fee: float = 0.0


class PaymentSubmitProof(BaseModel):
    proof_image_url: str


class PaymentReview(BaseModel):
    approved: bool
    rejection_reason: Optional[str] = None


class PaymentResponse(PaymentBase):
    id: UUID
    tanda_id: UUID
    round_id: UUID
    payer_user_id: UUID
    slot_number: int
    status: PaymentStatus
    proof_image_url: Optional[str] = None
    rejection_reason: Optional[str] = None
    verified_by_user_id: Optional[UUID] = None
    verified_at: Optional[datetime] = None
    created_at: datetime
    payer: Optional[UserResponse] = None

    model_config = ConfigDict(from_attributes=True)
