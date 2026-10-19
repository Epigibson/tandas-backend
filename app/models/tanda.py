import uuid
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, Float, Text, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.db.base import Base, TimestampMixin


class FrequencyType(str, enum.Enum):
    SEMANAL = "semanal"
    CATORCENAL = "catorcenal"
    QUINCENAL = "quincenal"
    MENSUAL = "mensual"


class AssignmentMethod(str, enum.Enum):
    MANUAL = "manual"
    FIRST_COME = "first_come"
    DRAW = "draw"


class TandaStatus(str, enum.Enum):
    DRAFT = "draft"
    RECRUITING = "recruiting"
    ACTIVE = "active"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class Tanda(Base, TimestampMixin):
    __tablename__ = "tandas"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    organizer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    
    currency: Mapped[str] = mapped_column(String(3), default="MXN")
    contribution_amount: Mapped[float] = mapped_column(Float, nullable=False)
    total_slots: Mapped[int] = mapped_column(Integer, nullable=False)
    payout_total: Mapped[float] = mapped_column(Float, nullable=False)

    frequency: Mapped[FrequencyType] = mapped_column(
        SQLEnum(FrequencyType),
        default=FrequencyType.QUINCENAL,
        nullable=False
    )
    assignment_method: Mapped[AssignmentMethod] = mapped_column(
        SQLEnum(AssignmentMethod),
        default=AssignmentMethod.DRAW,
        nullable=False
    )
    status: Mapped[TandaStatus] = mapped_column(
        SQLEnum(TandaStatus),
        default=TandaStatus.RECRUITING,
        nullable=False
    )

    # Reglas
    grace_period_days: Mapped[int] = mapped_column(Integer, default=2)
    late_fee_per_day: Mapped[float] = mapped_column(Float, default=0.0)
    require_proof_photo: Mapped[bool] = mapped_column(default=True)
    
    # Código de invitación para compartir por WhatsApp
    invite_code: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    
    start_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relaciones
    organizer = relationship("User", back_populates="organized_tandas", foreign_keys=[organizer_id])
    slots = relationship("TandaSlot", back_populates="tanda", cascade="all, delete-orphan", order_by="TandaSlot.slot_number")
    rounds = relationship("TandaRound", back_populates="tanda", cascade="all, delete-orphan", order_by="TandaRound.round_number")
    audit_logs = relationship("ActivityAuditLog", back_populates="tanda", cascade="all, delete-orphan")
