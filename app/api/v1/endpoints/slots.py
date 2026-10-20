from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.tanda import Tanda, TandaStatus
from app.models.slot import TandaSlot, PayoutStatus
from app.models.round import TandaRound, RoundStatus
from app.services.tanda_access import ensure_organizer
from app.services.tanda_service import close_round_and_advance
from app.services.realtime_service import notify_tanda_changed
from app.schemas.slot import TandaSlotResponse
from app.models.audit import ActivityAuditLog

router = APIRouter()


async def _load_slot_with_user(db: AsyncSession, slot_id: UUID) -> TandaSlot:
    # La respuesta incluye `user`; en async no se puede cargar de forma perezosa al serializar
    stmt = (
        select(TandaSlot)
        .where(TandaSlot.id == slot_id)
        .options(selectinload(TandaSlot.user))
        .execution_options(populate_existing=True)
    )
    res = await db.execute(stmt)
    return res.scalar_one()


@router.post("/{slot_id}/claim", response_model=TandaSlotResponse)
async def claim_slot(
    slot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Cualquier participante (o el organizador) puede apartar un turno libre para sí mismo.
    No hay límite: un familiar o usuario puede pedir 2, 3, 4 o los números que desee.
    """
    stmt = (
        select(TandaSlot)
        .where(TandaSlot.id == slot_id)
        .options(selectinload(TandaSlot.user))
    )
    res = await db.execute(stmt)
    slot = res.scalar_one_or_none()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
        
    if slot.user_id is not None:
        raise HTTPException(
            status_code=400,
            detail="Este turno ya fue apartado por otro participante"
        )
        
    tanda_res = await db.execute(select(Tanda).where(Tanda.id == slot.tanda_id))
    tanda = tanda_res.scalar_one_or_none()
    if not tanda or tanda.status not in ["recruiting", "draft"]:
        raise HTTPException(
            status_code=400,
            detail="No se pueden apartar turnos una vez iniciada o finalizada la tanda"
        )
        
    slot.user_id = current_user.id
    
    audit = ActivityAuditLog(
        tanda_id=slot.tanda_id,
        user_id=current_user.id,
        action="CLAIM_SLOT",
        description=f"{current_user.full_name} apartó el Turno #{slot.slot_number}."
    )
    db.add(audit)
    
    await db.commit()
    notify_tanda_changed(slot.tanda_id)
    
    stmt = select(TandaSlot).where(TandaSlot.id == slot_id).options(selectinload(TandaSlot.user))
    res = await db.execute(stmt)
    return res.scalar_one()


@router.post("/{slot_id}/release", response_model=TandaSlotResponse)
async def release_slot(
    slot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Permite liberar un turno apartado si la tanda aún está en reclutamiento.
    El propio titular del turno o el organizador pueden liberar el turno.
    """
    stmt = (
        select(TandaSlot)
        .where(TandaSlot.id == slot_id)
        .options(selectinload(TandaSlot.user))
    )
    res = await db.execute(stmt)
    slot = res.scalar_one_or_none()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
        
    tanda_res = await db.execute(select(Tanda).where(Tanda.id == slot.tanda_id))
    tanda = tanda_res.scalar_one_or_none()
    
    if not tanda or tanda.status not in ["recruiting", "draft"]:
        raise HTTPException(
            status_code=400,
            detail="No se pueden liberar turnos una vez iniciada la tanda"
        )
        
    if slot.user_id != current_user.id and tanda.organizer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el titular del turno o el organizador pueden liberarlo")
        
    slot.user_id = None
    
    audit = ActivityAuditLog(
        tanda_id=slot.tanda_id,
        user_id=current_user.id,
        action="RELEASE_SLOT",
        description=f"Se liberó el Turno #{slot.slot_number}."
    )
    db.add(audit)
    
    await db.commit()
    notify_tanda_changed(slot.tanda_id)
    
    stmt = select(TandaSlot).where(TandaSlot.id == slot_id).options(selectinload(TandaSlot.user))
    res = await db.execute(stmt)
    return res.scalar_one()


@router.put("/{slot_id}/assign-user", response_model=TandaSlotResponse)
async def assign_user_to_slot(
    slot_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(TandaSlot).where(TandaSlot.id == slot_id)
    res = await db.execute(stmt)
    slot = res.scalar_one_or_none()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
        
    tanda_res = await db.execute(select(Tanda).where(Tanda.id == slot.tanda_id))
    tanda = tanda_res.scalar_one_or_none()
    
    if not tanda:
        raise HTTPException(status_code=404, detail="Tanda no encontrada")
    ensure_organizer(tanda, current_user.id, "Solo el organizador puede asignar turnos manualmente")
    if tanda.status not in (TandaStatus.RECRUITING, TandaStatus.DRAFT):
        raise HTTPException(status_code=400, detail="No se pueden reasignar turnos una vez iniciada la tanda")

    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

    slot.user_id = user_id
    db.add(ActivityAuditLog(
        tanda_id=slot.tanda_id,
        user_id=current_user.id,
        action="ASSIGN_SLOT",
        description=f"El organizador asignó el Turno #{slot.slot_number} a {target.full_name}."
    ))
    await db.commit()
    notify_tanda_changed(slot.tanda_id)
    return await _load_slot_with_user(db, slot_id)


@router.post("/{slot_id}/confirm-payout", response_model=TandaSlotResponse)
async def confirm_payout_reception(
    slot_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    El beneficiario del turno confirma formalmente que ya recibió el dinero del pozo.
    """
    stmt = select(TandaSlot).where(TandaSlot.id == slot_id)
    res = await db.execute(stmt)
    slot = res.scalar_one_or_none()
    
    if not slot:
        raise HTTPException(status_code=404, detail="Turno no encontrado")
    
    if slot.user_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Solo el beneficiario asignado a este turno puede confirmar la recepción del dinero"
        )

    if slot.payout_status == PayoutStatus.CONFIRMED:
        raise HTTPException(status_code=400, detail="Ya habías confirmado la recepción de esta bolsa")

    round_stmt = select(TandaRound).where(
        TandaRound.tanda_id == slot.tanda_id,
        TandaRound.slot_number_beneficiary == slot.slot_number
    )
    tanda_round = (await db.execute(round_stmt)).scalar_one_or_none()
    if not tanda_round or tanda_round.status != RoundStatus.COMPLETED_PENDING_PAYOUT:
        raise HTTPException(
            status_code=400,
            detail="Tu bolsa todavía no está lista: falta reunir las aportaciones de tu ronda"
        )

    slot.payout_status = PayoutStatus.CONFIRMED
    slot.payout_confirmed_at = datetime.now(timezone.utc)
    await close_round_and_advance(db, tanda_round)

    audit = ActivityAuditLog(
        tanda_id=slot.tanda_id,
        user_id=current_user.id,
        action="PAYOUT_CONFIRMED",
        description=f"{current_user.full_name} confirmó la recepción del pozo del Turno #{slot.slot_number}."
    )
    db.add(audit)
    await db.commit()
    notify_tanda_changed(slot.tanda_id)
    return await _load_slot_with_user(db, slot_id)
