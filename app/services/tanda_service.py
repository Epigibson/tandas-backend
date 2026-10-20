import calendar
import secrets
import random
from datetime import datetime, timedelta, timezone
from typing import List
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.tanda import Tanda, FrequencyType, TandaStatus, AssignmentMethod
from app.models.slot import TandaSlot, PayoutStatus
from app.models.round import TandaRound, RoundStatus
from app.models.audit import ActivityAuditLog
from app.models.user import User


def generate_invite_code(prefix: str = "TANDA") -> str:
    token = secrets.token_hex(3).upper()
    return f"{prefix}-{token}"


# México no tiene horario de verano desde 2022: CDMX es UTC-6 todo el año
MEXICO_TZ = timezone(timedelta(hours=-6))


def _quincena_dates(start_date: datetime, total_slots: int) -> List[datetime]:
    """
    Cortes el día 15 y el último día de cada mes (fecha de México), empezando por el primero
    que caiga en o después del inicio. Se fijan a las 12:00 de CDMX para que el día no cambie al
    convertir entre UTC y hora local.
    """
    start_local = start_date.astimezone(MEXICO_TZ)
    dates: List[datetime] = []
    year, month = start_local.year, start_local.month
    while len(dates) < total_slots:
        last_day = calendar.monthrange(year, month)[1]
        for day in (15, last_day):
            candidate = datetime(year, month, day, 12, tzinfo=MEXICO_TZ)
            if candidate.date() >= start_local.date() and len(dates) < total_slots:
                dates.append(candidate.astimezone(timezone.utc))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return dates


def calculate_round_dates(start_date: datetime, frequency: FrequencyType, total_slots: int) -> List[datetime]:
    if frequency == FrequencyType.QUINCENAL:
        return _quincena_dates(start_date, total_slots)

    dates = []
    current_date = start_date

    for i in range(total_slots):
        dates.append(current_date)
        if frequency == FrequencyType.SEMANAL:
            current_date = current_date + timedelta(days=7)
        elif frequency == FrequencyType.CATORCENAL:
            current_date = current_date + timedelta(days=14)
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
            # Ninguna ronda recauda hasta que el organizador inicia la tanda (start_tanda)
            status=RoundStatus.UPCOMING
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


async def start_tanda(db: AsyncSession, tanda: Tanda, user_id: UUID) -> None:
    """
    Cierra el reclutamiento y arranca la ronda 1. Requiere `tanda.slots` y `tanda.rounds` cargados.
    Las fechas se recalculan desde hoy (o desde la fecha de inicio pactada, si es futura).
    """
    if tanda.status not in (TandaStatus.RECRUITING, TandaStatus.DRAFT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La tanda ya fue iniciada")

    empty_slots = sum(1 for s in tanda.slots if s.user_id is None)
    if empty_slots:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Faltan {empty_slots} lugares por apartar antes de iniciar la tanda"
        )

    now = datetime.now(timezone.utc)
    start = tanda.start_date if tanda.start_date and tanda.start_date > now else now
    dates = calculate_round_dates(start, tanda.frequency, tanda.total_slots)
    slots_by_number = {s.slot_number: s for s in tanda.slots}

    for rnd in tanda.rounds:
        rnd.due_date = dates[rnd.round_number - 1]
        rnd.status = RoundStatus.COLLECTING if rnd.round_number == 1 else RoundStatus.UPCOMING
        beneficiary = slots_by_number.get(rnd.slot_number_beneficiary)
        if beneficiary:
            beneficiary.scheduled_payout_date = rnd.due_date

    tanda.status = TandaStatus.ACTIVE
    tanda.start_date = start
    tanda.end_date = dates[-1]

    db.add(ActivityAuditLog(
        tanda_id=tanda.id,
        user_id=user_id,
        action="TANDA_STARTED",
        description=f"La tanda '{tanda.title}' inició. Primera ronda recaudando."
    ))
    await db.commit()


async def close_round_and_advance(db: AsyncSession, tanda_round: TandaRound) -> None:
    """
    Tras confirmar la entrega de la bolsa: cierra la ronda y abre la siguiente.
    Si era la última, la tanda queda completada. No hace commit.
    """
    now = datetime.now(timezone.utc)
    tanda_round.status = RoundStatus.CLOSED
    tanda_round.closed_at = now

    next_stmt = select(TandaRound).where(
        TandaRound.tanda_id == tanda_round.tanda_id,
        TandaRound.round_number == tanda_round.round_number + 1
    )
    next_round = (await db.execute(next_stmt)).scalar_one_or_none()
    if next_round:
        next_round.status = RoundStatus.COLLECTING
        return

    tanda = (await db.execute(select(Tanda).where(Tanda.id == tanda_round.tanda_id))).scalar_one()
    tanda.status = TandaStatus.COMPLETED
    tanda.end_date = now

    member_ids = set((await db.execute(
        select(TandaSlot.user_id).where(TandaSlot.tanda_id == tanda.id, TandaSlot.user_id.is_not(None))
    )).scalars().all())
    if member_ids:
        members = (await db.execute(select(User).where(User.id.in_(member_ids)))).scalars().all()
        for member in members:
            member.tandas_completed += 1

    db.add(ActivityAuditLog(
        tanda_id=tanda.id,
        user_id=None,
        action="TANDA_COMPLETED",
        description=f"La tanda '{tanda.title}' terminó: todos los turnos cobraron."
    ))
