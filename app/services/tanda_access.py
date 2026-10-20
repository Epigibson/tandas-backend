from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.tanda import Tanda
from app.models.slot import TandaSlot


async def count_user_slots(db: AsyncSession, tanda_id: UUID, user_id: UUID) -> int:
    stmt = select(func.count(TandaSlot.id)).where(
        TandaSlot.tanda_id == tanda_id,
        TandaSlot.user_id == user_id
    )
    res = await db.execute(stmt)
    return res.scalar_one()


async def ensure_member(db: AsyncSession, tanda: Tanda, user_id: UUID) -> None:
    """
    Solo el organizador o quien tenga al menos un turno puede ver la tanda.
    Responde 404 (no 403) para no revelar qué tandas existen.
    """
    if tanda.organizer_id == user_id:
        return
    if await count_user_slots(db, tanda.id, user_id) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tanda no encontrada"
        )


def ensure_organizer(tanda: Tanda, user_id: UUID, detail: str) -> None:
    if tanda.organizer_id != user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)
