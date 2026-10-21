import calendar
import secrets
from datetime import datetime, timedelta, timezone
from typing import List
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
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


def ensure_not_started(tanda: Tanda, detail: str) -> None:
    if tanda.status not in (TandaStatus.RECRUITING, TandaStatus.DRAFT):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def normalize_start_date(start_date: datetime) -> datetime:
    """La fecha de inicio no puede quedar antes de hoy (fecha de México). Sin zona se toma como UTC."""
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    today_mx = datetime.now(MEXICO_TZ).date()
    if start_date.astimezone(MEXICO_TZ).date() < today_mx:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La fecha de inicio no puede ser anterior a hoy"
        )
    return start_date


def _apply_schedule(tanda: Tanda) -> None:
    """Recalcula bolsa y fechas de turnos y rondas. Requiere `tanda.slots` y `tanda.rounds` cargados."""
    start = tanda.start_date or datetime.now(timezone.utc)
    dates = calculate_round_dates(start, tanda.frequency, tanda.total_slots)
    tanda.payout_total = tanda.contribution_amount * tanda.total_slots
    for slot in tanda.slots:
        slot.scheduled_payout_date = dates[slot.slot_number - 1]
    for rnd in tanda.rounds:
        rnd.due_date = dates[rnd.round_number - 1]
        rnd.expected_amount = tanda.payout_total


async def update_tanda_config(db: AsyncSession, tanda: Tanda, changes: dict, user_id: UUID) -> None:
    """
    Edita una tanda que aún no inicia. Al cambiar el número de lugares se agregan o quitan
    los últimos; no se puede quitar uno que ya esté apartado. Requiere `slots` y `rounds` cargados.
    """
    ensure_not_started(tanda, "Solo se puede editar una tanda que aún no inicia")

    if changes.get("start_date") is not None:
        changes["start_date"] = normalize_start_date(changes["start_date"])
    for field in ("title", "description", "contribution_amount", "frequency", "assignment_method", "start_date"):
        if field in changes and (changes[field] is not None or field == "description"):
            setattr(tanda, field, changes[field])

    new_total = changes.get("total_slots")
    method_changed = "assignment_method" in changes  # ya se aplicó arriba
    if method_changed or (new_total is not None and new_total != tanda.total_slots):
        # Con otros lugares u otra forma de asignar, el sorteo anterior ya no vale
        tanda.numbers_drawn_at = None
    if new_total is not None and new_total != tanda.total_slots:
        if new_total < tanda.total_slots:
            taken = sorted(s.slot_number for s in tanda.slots if s.slot_number > new_total and s.user_id is not None)
            if taken:
                numbers = ", ".join(f"#{n}" for n in taken)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"No se puede bajar a {new_total} lugares: {numbers} ya están apartados. Libéralos primero."
                )
            for slot in [s for s in tanda.slots if s.slot_number > new_total]:
                tanda.slots.remove(slot)
            for rnd in [r for r in tanda.rounds if r.round_number > new_total]:
                tanda.rounds.remove(rnd)
        else:
            for n in range(tanda.total_slots + 1, new_total + 1):
                tanda.slots.append(TandaSlot(slot_number=n, payout_status=PayoutStatus.PENDING))
                tanda.rounds.append(TandaRound(
                    round_number=n,
                    slot_number_beneficiary=n,
                    due_date=datetime.now(timezone.utc),  # _apply_schedule pone la fecha real
                    expected_amount=0.0,
                    collected_amount=0.0,
                    status=RoundStatus.UPCOMING,
                ))
        tanda.total_slots = new_total

    _apply_schedule(tanda)
    db.add(ActivityAuditLog(
        tanda_id=tanda.id,
        user_id=user_id,
        action="TANDA_UPDATED",
        description=f"El organizador editó la tanda '{tanda.title}'."
    ))
    await db.commit()


async def assign_on_join(db: AsyncSession, tanda: Tanda, user_id: UUID, slot_numbers: List[int]) -> None:
    """
    Aparta lugares a quien entra con el código. En elección libre se respetan los números que
    eligió; en sorteo o manual se toma el primer lugar libre (el número real lo define el organizador).
    La actualización es condicional para que dos personas no se queden con el mismo número.
    """
    free_numbers = sorted(s.slot_number for s in tanda.slots if s.user_id is None)
    if not free_numbers:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La tanda ya está llena")

    if tanda.assignment_method == AssignmentMethod.FIRST_COME:
        wanted = sorted(set(slot_numbers))
        if not wanted:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Elige tu número antes de entrar a la tanda"
            )
        if any(n < 1 or n > tanda.total_slots for n in wanted):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Ese número no existe en la tanda")
    else:
        wanted = free_numbers[:1]

    result = await db.execute(
        update(TandaSlot)
        .where(
            TandaSlot.tanda_id == tanda.id,
            TandaSlot.slot_number.in_(wanted),
            TandaSlot.user_id.is_(None),
        )
        .values(user_id=user_id)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != len(wanted):
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Alguien más acaba de apartar uno de esos números. Elige otro."
        )

    numbers = ", ".join(f"#{n}" for n in wanted)
    db.add(ActivityAuditLog(
        tanda_id=tanda.id,
        user_id=user_id,
        action="JOINED",
        description=f"Se unió a la tanda con {'los números' if len(wanted) > 1 else 'el número'} {numbers}."
    ))
    await db.commit()


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
            # En sorteo el organizador ya ocupa un lugar (su número sale en el sorteo);
            # en elección libre escoge su número como todos
            user_id=tanda.organizer_id if i == 1 and tanda.assignment_method != AssignmentMethod.FIRST_COME else None,
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


async def execute_lottery_draw(db: AsyncSession, tanda: Tanda, user_id: UUID) -> None:
    """
    Reparte los números al azar entre los lugares apartados. Solo con la tanda llena y una sola vez
    (se vuelve a permitir si cambian los lugares al editar la tanda).
    """
    if tanda.assignment_method != AssignmentMethod.DRAW:
        raise HTTPException(status_code=400, detail="En elección libre cada quien escoge su número; no hay sorteo")
    if tanda.numbers_drawn_at is not None:
        raise HTTPException(status_code=400, detail="El sorteo ya se hizo")

    stmt = select(TandaSlot).where(TandaSlot.tanda_id == tanda.id).order_by(TandaSlot.slot_number)
    slots = list((await db.execute(stmt)).scalars().all())
    empty = sum(1 for slot in slots if slot.user_id is None)
    if empty:
        raise HTTPException(
            status_code=400,
            detail=f"Faltan {empty} {'lugar' if empty == 1 else 'lugares'} por llenar antes del sorteo"
        )

    user_ids = [slot.user_id for slot in slots]
    # SystemRandom: el orden no se puede predecir a partir de sorteos anteriores
    secrets.SystemRandom().shuffle(user_ids)
    for slot, new_user_id in zip(slots, user_ids):
        slot.user_id = new_user_id

    tanda.numbers_drawn_at = datetime.now(timezone.utc)
    db.add(ActivityAuditLog(
        tanda_id=tanda.id,
        user_id=user_id,
        action="LOTTERY_DRAW",
        description=f"Se sortearon los {len(slots)} números de la tanda '{tanda.title}'."
    ))
    await db.commit()


async def start_tanda(db: AsyncSession, tanda: Tanda, user_id: UUID) -> None:
    """
    Cierra el reclutamiento y arranca la ronda 1. Requiere `tanda.slots` y `tanda.rounds` cargados.
    Las fechas se recalculan desde hoy (o desde la fecha de inicio pactada, si es futura).
    """
    ensure_not_started(tanda, "La tanda ya fue iniciada")
    if tanda.assignment_method == AssignmentMethod.DRAW and tanda.numbers_drawn_at is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Primero haz el sorteo de números"
        )

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
