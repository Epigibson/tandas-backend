import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import Integer, Float, String, ForeignKey, DateTime, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
import enum
from app.db.base import Base, TimestampMixin


class PaymentStatus(str, enum.Enum):
    PENDING_UPLOAD = "pending_upload"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"

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
    round_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tanda_rounds.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    payer_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True
    )
    slot_number: Mapped[int] = mapped_column(Integer, nullable=False)
    
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    late_fee: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[PaymentStatus] = mapped_column(
        SQLEnum(PaymentStatus),
        default=PaymentStatus.PENDING_UPLOAD,
        nullable=False
    )
    proof_image_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    rejection_reason: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)

    verified_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relaciones
    payer = relationship("User", foreign_keys=[payer_user_id], back_populates="payments")
    round = relationship("TandaRound", back_populates="payments")
