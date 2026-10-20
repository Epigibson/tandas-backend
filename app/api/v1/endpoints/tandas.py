from typing import List
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, delete
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.tanda import Tanda, TandaStatus, AssignmentMethod
from app.models.slot import TandaSlot
from app.models.round import RoundStatus
from app.models.slot import PayoutStatus
from app.schemas.tanda import (
    TandaCreate,
    TandaUpdate,
    TandaResponse,
    TandaDetailResponse,
    TandaSummaryResponse,
    JoinTandaRequest,
    TandaInvitePreview,
    InviteSlotPreview,
)
from app.services.tanda_service import (
    generate_invite_code,
    initialize_tanda_slots_and_rounds,
    execute_lottery_draw,
    start_tanda,
    ensure_not_started,
    normalize_start_date,
    update_tanda_config,
    assign_on_join,
)
from app.services.tanda_access import ensure_member, ensure_organizer, ensure_superuser, count_user_slots
from app.services.credentials_service import create_reset_code
from app.models.audit import ActivityAuditLog
from app.schemas.auth import ResetCodeResponse
from app.services.realtime_service import notify_tanda_changed

router = APIRouter()


@router.post("", response_model=TandaResponse, status_code=status.HTTP_201_CREATED)
async def create_tanda(
    tanda_in: TandaCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    start_date = normalize_start_date(tanda_in.start_date) if tanda_in.start_date else datetime.now(timezone.utc)
    payout_total = tanda_in.contribution_amount * tanda_in.total_slots
    
    tanda = Tanda(
        title=tanda_in.title,
        description=tanda_in.description,
        organizer_id=current_user.id,
        contribution_amount=tanda_in.contribution_amount,
        total_slots=tanda_in.total_slots,
        payout_total=payout_total,
        frequency=tanda_in.frequency,
        assignment_method=tanda_in.assignment_method,
        status=TandaStatus.RECRUITING,
        grace_period_days=tanda_in.grace_period_days,
        late_fee_per_day=tanda_in.late_fee_per_day,
        require_proof_photo=tanda_in.require_proof_photo,
        invite_code=generate_invite_code(),
        start_date=start_date
    )
    db.add(tanda)
    await db.commit()
    await db.refresh(tanda)

    # Inicializar slots y fechas de cortes/rondas
    await initialize_tanda_slots_and_rounds(db, tanda, start_date)

    return tanda


@router.get("", response_model=List[TandaSummaryResponse])
async def list_my_tandas(
    all_tandas: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Tandas donde soy organizador O donde tengo un slot asignado; el admin puede pedir todas
    stmt = select(Tanda)
    if all_tandas:
        ensure_superuser(current_user)
    else:
        stmt = (
            stmt.outerjoin(TandaSlot, Tanda.id == TandaSlot.tanda_id)
            .where(
                or_(
                    Tanda.organizer_id == current_user.id,
                    TandaSlot.user_id == current_user.id
                )
            )
            .distinct()
        )
    stmt = (
        stmt.options(
            selectinload(Tanda.organizer),
            selectinload(Tanda.slots),
            selectinload(Tanda.rounds)
        )
    )
    result = await db.execute(stmt)
    return [_build_summary(tanda, current_user.id) for tanda in result.scalars().all()]


def _build_summary(tanda: Tanda, user_id: UUID) -> TandaSummaryResponse:
    """Agrega al listado lo que el Home necesita sin pedir el detalle de cada tanda."""
    collecting = next((r for r in tanda.rounds if r.status == RoundStatus.COLLECTING), None)
    my_slots = sorted((s for s in tanda.slots if s.user_id == user_id), key=lambda s: s.slot_number)
    pending_payouts = [
        s.scheduled_payout_date for s in my_slots
        if s.payout_status != PayoutStatus.CONFIRMED and s.scheduled_payout_date is not None
    ]

    summary = TandaSummaryResponse.model_validate(tanda)
    summary.current_round_number = collecting.round_number if collecting else None
    summary.my_slot_numbers = [s.slot_number for s in my_slots]
    summary.my_next_payout_date = min(pending_payouts) if pending_payouts else None
    return summary


async def _load_tanda_detail(db: AsyncSession, tanda_id: UUID) -> Tanda:
    stmt = (
        select(Tanda)
        .where(Tanda.id == tanda_id)
        .options(
            selectinload(Tanda.organizer),
            selectinload(Tanda.slots).selectinload(TandaSlot.user),
            selectinload(Tanda.rounds)
        )
    )
    result = await db.execute(stmt)
    tanda = result.scalar_one_or_none()
    
    if not tanda:
        raise HTTPException(status_code=404, detail="Tanda no encontrada")
    return tanda


@router.get("/{tanda_id}", response_model=TandaDetailResponse)
async def get_tanda(
    tanda_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    tanda = await _load_tanda_detail(db, tanda_id)
    await ensure_member(db, tanda, current_user)
    return tanda


@router.post("/{tanda_id}/start", response_model=TandaDetailResponse)
async def start_tanda_endpoint(
    tanda_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """El organizador cierra el reclutamiento y arranca la primera ronda."""
    tanda = await _load_tanda_detail(db, tanda_id)
    ensure_organizer(tanda, current_user, "Solo el organizador puede iniciar la tanda")
    await start_tanda(db, tanda, current_user.id)
    notify_tanda_changed(tanda_id)
    # Recargar desde cero: el commit expira los objetos ya cargados
    db.expire_all()
    return await _load_tanda_detail(db, tanda_id)


async def _load_by_invite(db: AsyncSession, invite_code: str) -> Tanda:
    stmt = (
        select(Tanda)
        .where(Tanda.invite_code == invite_code.upper().strip())
        .options(
            selectinload(Tanda.organizer),
            selectinload(Tanda.slots).selectinload(TandaSlot.user),
            selectinload(Tanda.rounds)
        )
    )
    tanda = (await db.execute(stmt)).scalar_one_or_none()
    if not tanda:
        raise HTTPException(status_code=404, detail="Código de invitación no válido o expirado")
    return tanda


@router.get("/invite/{invite_code}", response_model=TandaInvitePreview)
async def preview_invite(
    invite_code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Muestra la tanda y los números libres antes de unirse, para que cada quien elija el suyo."""
    tanda = await _load_by_invite(db, invite_code)
    return TandaInvitePreview(
        id=tanda.id,
        title=tanda.title,
        description=tanda.description,
        organizer_name=tanda.organizer.full_name,
        contribution_amount=tanda.contribution_amount,
        total_slots=tanda.total_slots,
        payout_total=tanda.payout_total,
        frequency=tanda.frequency,
        assignment_method=tanda.assignment_method,
        status=tanda.status,
        start_date=tanda.start_date,
        already_member=tanda.organizer_id == current_user.id
        or any(s.user_id == current_user.id for s in tanda.slots),
        slots=[
            InviteSlotPreview(
                slot_number=s.slot_number,
                taken=s.user_id is not None,
                # Solo el nombre de pila: el código puede llegar a alguien fuera de la familia
                holder_first_name=s.user.full_name.split(" ")[0] if s.user else None,
                is_mine=s.user_id == current_user.id,
                scheduled_payout_date=s.scheduled_payout_date,
            )
            for s in tanda.slots
        ],
    )


@router.post("/join/{invite_code}", response_model=TandaDetailResponse)
async def join_tanda_by_invite(
    invite_code: str,
    join_in: JoinTandaRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    tanda = await _load_by_invite(db, invite_code)

    already_member = any(slot.user_id == current_user.id for slot in tanda.slots)
    if already_member or tanda.organizer_id == current_user.id:
        return tanda

    ensure_not_started(tanda, "Esta tanda ya inició y no acepta nuevos participantes")
    tanda_id = tanda.id  # leerlo después de expire_all dispararía una carga síncrona
    await assign_on_join(db, tanda, current_user.id, join_in.slot_numbers if join_in else [])
    notify_tanda_changed(tanda_id)
    db.expire_all()
    return await _load_tanda_detail(db, tanda_id)


@router.patch("/{tanda_id}", response_model=TandaDetailResponse)
async def update_tanda(
    tanda_id: UUID,
    tanda_in: TandaUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """El organizador cambia la configuración mientras la tanda no inicia."""
    tanda = await _load_tanda_detail(db, tanda_id)
    ensure_organizer(tanda, current_user, "Solo el organizador puede editar la tanda")
    await update_tanda_config(db, tanda, tanda_in.model_dump(exclude_unset=True), current_user.id)
    notify_tanda_changed(tanda_id)
    db.expire_all()
    return await _load_tanda_detail(db, tanda_id)


@router.delete("/{tanda_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tanda(
    tanda_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Borra una tanda que no ha iniciado; turnos, rondas y bitácora se van en cascada en la BD."""
    tanda = (await db.execute(select(Tanda).where(Tanda.id == tanda_id))).scalar_one_or_none()
    if not tanda:
        raise HTTPException(status_code=404, detail="Tanda no encontrada")
    ensure_organizer(tanda, current_user, "Solo el organizador puede eliminar la tanda")
    ensure_not_started(tanda, "Solo se puede eliminar una tanda que aún no inicia")
    await db.execute(delete(Tanda).where(Tanda.id == tanda_id))
    await db.commit()
    notify_tanda_changed(tanda_id)


@router.post("/{tanda_id}/draw", response_model=TandaDetailResponse)
async def trigger_lottery_draw(
    tanda_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(Tanda).where(Tanda.id == tanda_id)
    res = await db.execute(stmt)
    tanda = res.scalar_one_or_none()
    
    if not tanda:
        raise HTTPException(status_code=404, detail="Tanda no encontrada")
    ensure_organizer(tanda, current_user, "Solo el organizador puede ejecutar el sorteo de números")
    # Sortear con la tanda en curso revolvería turnos que ya cobraron o están cobrando
    ensure_not_started(tanda, "El sorteo solo se puede hacer antes de iniciar la tanda")
    if tanda.assignment_method == AssignmentMethod.FIRST_COME:
        raise HTTPException(status_code=400, detail="En elección libre cada quien escoge su número; no hay sorteo")
    
    await execute_lottery_draw(db, tanda_id)
    notify_tanda_changed(tanda_id)
    db.expire_all()
    return await _load_tanda_detail(db, tanda_id)


@router.post("/{tanda_id}/members/{user_id}/reset-code", response_model=ResetCodeResponse)
async def create_member_reset_code(
    tanda_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    El organizador genera un código temporal (30 min) para que un miembro de su tanda
    que olvidó su contraseña pueda cambiarla desde el login.
    """
    tanda = (await db.execute(select(Tanda).where(Tanda.id == tanda_id))).scalar_one_or_none()
    if not tanda:
        raise HTTPException(status_code=404, detail="Tanda no encontrada")
    ensure_organizer(tanda, current_user, "Solo el organizador puede generar códigos para restablecer contraseña")
    if user_id == current_user.id:
        raise HTTPException(status_code=400, detail="Para cambiar tu propia contraseña no necesitas un código")
    if not current_user.is_superuser and await count_user_slots(db, tanda_id, user_id) == 0:
        raise HTTPException(status_code=404, detail="Esa persona no participa en esta tanda")

    code, expires_at = await create_reset_code(db, user_id, current_user.id)
    db.add(ActivityAuditLog(
        tanda_id=tanda_id,
        user_id=current_user.id,
        action="RESET_CODE_CREATED",
        description="El organizador generó un código para restablecer la contraseña de un participante.",
    ))
    await db.commit()
    return ResetCodeResponse(code=code, expires_at=expires_at)
