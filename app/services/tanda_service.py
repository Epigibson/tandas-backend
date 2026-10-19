import secrets
import random
from datetime import datetime, timedelta, timezone
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.tanda import Tanda, FrequencyType, TandaStatus, AssignmentMethod
from app.models.slot import TandaSlot, PayoutStatus
from app.models.round import TandaRound, RoundStatus
from app.models.audit import ActivityAuditLog


def generate_invite_code(prefix: str = "TANDA") -> str:
    token = secrets.token_hex(3).upper()
    return f"{prefix}-{token}"


def calculate_round_dates(start_date: datetime, frequency: FrequencyType, total_slots: int) -> List[datetime]:
    dates = []
    current_date = start_date

    for i in range(total_slots):
        dates.append(current_date)
        if frequency == FrequencyType.SEMANAL:
            current_date = current_date + timedelta(days=7)
        elif frequency == FrequencyType.CATORCENAL:
            current_date = current_date + timedelta(days=14)
        elif frequency == FrequencyType.QUINCENAL:
            current_date = current_date + timedelta(days=15)
        elif frequency == FrequencyType.MENSUAL:
            # Aproximación mensual estándar de 30 días
            current_date = current_date + timedelta(days=30)
    
    return dates


async def initialize_tanda_slots_and_rounds(
    db: AsyncSession,
    tanda: Tanda,
    start_date: datetime
) -> None:
    dates = calculate_round_dates(start_date, tanda.frequency, tanda.total_slots)
    
    # 1. Crear los Slots (Turnos)
    for i in range(1, tanda.total_slots + 1):
        slot = TandaSlot(
            tanda_id=tanda.id,
            slot_number=i,
            user_id=tanda.organizer_id if i == 1 else None, # Por tradición mexicana, el organizador suele tomar el número 1
            scheduled_payout_date=dates[i - 1],
            payout_status=PayoutStatus.PENDING
        )
        db.add(slot)
    
    # 2. Crear las Rondas (Cortes de pago)
    for i in range(1, tanda.total_slots + 1):
        rnd = TandaRound(
            tanda_id=tanda.id,
            round_number=i,
            slot_number_beneficiary=i,
            due_date=dates[i - 1],
            expected_amount=tanda.payout_total,
            collected_amount=0.0,
            status=RoundStatus.UPCOMING if i > 1 else RoundStatus.COLLECTING
        )
        db.add(rnd)

    # 3. Log de auditoría
    audit = ActivityAuditLog(
        tanda_id=tanda.id,
        user_id=tanda.organizer_id,
        action="TANDA_INITIALIZED",
        description=f"Tanda '{tanda.title}' creada con {tanda.total_slots} turnos ({tanda.frequency.value})."
    )
    db.add(audit)
    await db.commit()


async def execute_lottery_draw(
    db: AsyncSession,
    tanda_id: UUID
) -> List[TandaSlot]:
    """
    Sortea aleatoriamente los miembros asignados a una tanda entre los turnos disponibles.
    """
    stmt = select(TandaSlot).where(TandaSlot.tanda_id == tanda_id).order_by(TandaSlot.slot_number)
    res = await db.execute(stmt)
    slots = list(res.scalars().all())

    # Obtenemos todos los user_id asignados
    user_ids = [slot.user_id for slot in slots if slot.user_id is not None]
    
    # Barajamos aleatoriamente
    random.shuffle(user_ids)

    # Reasignamos
    for i, user_id in enumerate(user_ids):
        slots[i].user_id = user_id

    await db.commit()
    return slots
