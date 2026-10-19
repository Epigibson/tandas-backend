from uuid import UUID
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.tanda import Tanda
from app.models.slot import TandaSlot, PayoutStatus
from app.schemas.slot import TandaSlotResponse
from app.models.audit import ActivityAuditLog

router = APIRouter()


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
    
    if not tanda or tanda.organizer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo el organizador puede asignar turnos manualmente")

    slot.user_id = user_id
    await db.commit()
    await db.refresh(slot)
    return slot


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

    slot.payout_status = PayoutStatus.CONFIRMED
    slot.payout_confirmed_at = datetime.now(timezone.utc)

    audit = ActivityAuditLog(
        tanda_id=slot.tanda_id,
        user_id=current_user.id,
        action="PAYOUT_CONFIRMED",
        description=f"{current_user.full_name} confirmó la recepción del pozo del Turno #{slot.slot_number}."
    )
    db.add(audit)
    await db.commit()
    await db.refresh(slot)
    return slot
