import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, String, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.db.base import Base, TimestampMixin


class PayoutStatus(str, enum.Enum):
    PENDING = "pending"
    READY_TO_PAY = "ready_to_pay"
    PAID = "paid"
    CONFIRMED = "confirmed"


class TandaSlot(Base, TimestampMixin):
    __tablename__ = "tanda_slots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    tanda_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tandas.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True
    )
    
    scheduled_payout_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    payout_status: Mapped[PayoutStatus] = mapped_column(
        SQLEnum(PayoutStatus),
        default=PayoutStatus.PENDING,
        nullable=False
    )
    payout_proof_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    payout_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relaciones
    tanda = relationship("Tanda", back_populates="slots")
    user = relationship("User", back_populates="slots")
