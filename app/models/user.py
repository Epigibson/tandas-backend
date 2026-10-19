import uuid
from typing import Optional, List
from sqlalchemy import String, Integer, Boolean, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID
from app.db.base import Base, TimestampMixin


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4
    )
    phone: Mapped[str] = mapped_column(String(20), unique=True, index=True, nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255), unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(150), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    avatar_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    clabe: Mapped[Optional[str]] = mapped_column(String(18), nullable=True)
    bank_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    fcm_token: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    
    # Reputación / TandaScore
    tanda_score: Mapped[int] = mapped_column(Integer, default=100)
    tandas_completed: Mapped[int] = mapped_column(Integer, default=0)
    on_time_payments: Mapped[int] = mapped_column(Integer, default=0)
    late_payments: Mapped[int] = mapped_column(Integer, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)

    # Relaciones
    organized_tandas = relationship("Tanda", back_populates="organizer", foreign_keys="Tanda.organizer_id")
    slots = relationship("TandaSlot", back_populates="user")
    payments = relationship("Payment", back_populates="payer", foreign_keys="Payment.payer_user_id")
