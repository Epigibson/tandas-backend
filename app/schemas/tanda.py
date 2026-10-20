from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field
from app.models.tanda import FrequencyType, AssignmentMethod, TandaStatus
from app.schemas.user import UserResponse
from app.schemas.slot import TandaSlotResponse
from app.schemas.round import TandaRoundResponse


class TandaBase(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    contribution_amount: float = Field(gt=0)
    total_slots: int = Field(ge=2, le=50)
    frequency: FrequencyType = FrequencyType.QUINCENAL
    assignment_method: AssignmentMethod = AssignmentMethod.DRAW
    grace_period_days: int = 2
    late_fee_per_day: float = 0.0
    require_proof_photo: bool = True
    start_date: Optional[datetime] = None


class TandaCreate(TandaBase):
    pass


class TandaUpdate(BaseModel):
    """Solo antes de iniciar. Los campos que no se manden se quedan como están."""
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    contribution_amount: Optional[float] = Field(default=None, gt=0)
    total_slots: Optional[int] = Field(default=None, ge=2, le=50)
    frequency: Optional[FrequencyType] = None
    assignment_method: Optional[AssignmentMethod] = None
    start_date: Optional[datetime] = None


class JoinTandaRequest(BaseModel):
    # En elección libre es obligatorio; en sorteo se ignora y se toma cualquier lugar libre
    slot_numbers: List[int] = []


class InviteSlotPreview(BaseModel):
    slot_number: int
    taken: bool
    holder_first_name: Optional[str] = None
    is_mine: bool = False
    scheduled_payout_date: Optional[datetime] = None


class TandaInvitePreview(BaseModel):
    """Lo que ve quien tiene el código antes de unirse."""
    id: UUID
    title: str
    description: Optional[str] = None
    organizer_name: str
    contribution_amount: float
    total_slots: int
    payout_total: float
    frequency: FrequencyType
    assignment_method: AssignmentMethod
    status: TandaStatus
    start_date: Optional[datetime] = None
    already_member: bool
    slots: List[InviteSlotPreview]


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


class TandaSummaryResponse(TandaResponse):
    """Elemento del listado: incluye el avance y los turnos del usuario que consulta."""
    current_round_number: Optional[int] = None
    my_slot_numbers: List[int] = []
    my_next_payout_date: Optional[datetime] = None


class TandaDetailResponse(TandaResponse):
    slots: List[TandaSlotResponse] = []
    rounds: List[TandaRoundResponse] = []
