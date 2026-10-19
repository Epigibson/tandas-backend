import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import Integer, Float, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.db.base import Base, TimestampMixin


class RoundStatus(str, enum.Enum):
    UPCOMING = "upcoming"
    COLLECTING = "collecting"
    COMPLETED_PENDING_PAYOUT = "completed_pending_payout"
    CLOSED = "closed"


class TandaRound(Base, TimestampMixin):
    __tablename__ = "tanda_rounds"

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
    round_number: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_number_beneficiary: Mapped[int] = mapped_column(Integer, nullable=False)
    
    due_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_amount: Mapped[float] = mapped_column(Float, nullable=False)
    collected_amount: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[RoundStatus] = mapped_column(
        SQLEnum(RoundStatus),
        default=RoundStatus.UPCOMING,
        nullable=False
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relaciones
    tanda = relationship("Tanda", back_populates="rounds")
    payments = relationship("Payment", back_populates="round", cascade="all, delete-orphan")
