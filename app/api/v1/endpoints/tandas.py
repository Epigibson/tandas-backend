from typing import List
from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.tanda import Tanda, TandaStatus
from app.models.slot import TandaSlot
from app.schemas.tanda import TandaCreate, TandaResponse, TandaDetailResponse
from app.services.tanda_service import generate_invite_code, initialize_tanda_slots_and_rounds, execute_lottery_draw

router = APIRouter()


@router.post("", response_model=TandaResponse, status_code=status.HTTP_201_CREATED)
async def create_tanda(
    tanda_in: TandaCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    start_date = tanda_in.start_date or datetime.now(timezone.utc)
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


@router.get("", response_model=List[TandaResponse])
async def list_my_tandas(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    # Tandas donde soy organizador O donde tengo un slot asignado
    stmt = (
        select(Tanda)
        .outerjoin(TandaSlot, Tanda.id == TandaSlot.tanda_id)
        .where(
            or_(
                Tanda.organizer_id == current_user.id,
                TandaSlot.user_id == current_user.id
            )
        )
        .distinct()
        .options(selectinload(Tanda.organizer))
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{tanda_id}", response_model=TandaDetailResponse)
async def get_tanda(
    tanda_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
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


@router.post("/join/{invite_code}", response_model=TandaDetailResponse)
async def join_tanda_by_invite(
    invite_code: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = (
        select(Tanda)
        .where(Tanda.invite_code == invite_code.upper().strip())
        .options(
            selectinload(Tanda.organizer),
            selectinload(Tanda.slots).selectinload(TandaSlot.user),
            selectinload(Tanda.rounds)
        )
    )
    result = await db.execute(stmt)
    tanda = result.scalar_one_or_none()
    
    if not tanda:
        raise HTTPException(status_code=404, detail="Código de invitación no válido o expirado")
    
    # Verificar si el usuario ya está en la tanda
    already_member = any(slot.user_id == current_user.id for slot in tanda.slots)
    if already_member or tanda.organizer_id == current_user.id:
        return tanda

    # Asignar primer slot libre si está disponible
    empty_slot = next((s for s in tanda.slots if s.user_id is None), None)
    if not empty_slot:
        raise HTTPException(
            status_code=400,
            detail="La tanda ya tiene todos los turnos ocupados"
        )
    
    empty_slot.user_id = current_user.id
    await db.commit()
    await db.refresh(tanda)
    return tanda


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
    if tanda.organizer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el organizador puede ejecutar el sorteo de números")
    
    await execute_lottery_draw(db, tanda_id)
    return await get_tanda(tanda_id=tanda_id, current_user=current_user, db=db)
