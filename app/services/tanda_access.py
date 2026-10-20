from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models.tanda import Tanda
from app.models.slot import TandaSlot
from app.models.user import User


async def count_user_slots(db: AsyncSession, tanda_id: UUID, user_id: UUID) -> int:
    stmt = select(func.count(TandaSlot.id)).where(
        TandaSlot.tanda_id == tanda_id,
        TandaSlot.user_id == user_id
    )
    res = await db.execute(stmt)
    return res.scalar_one()


def can_manage(tanda: Tanda, user: User) -> bool:
    """El organizador de la tanda o un super admin (se activa a mano en la BD, nunca desde la app)."""
    return tanda.organizer_id == user.id or user.is_superuser


async def ensure_member(db: AsyncSession, tanda: Tanda, user: User) -> None:
    """
    Solo el organizador, quien tenga al menos un turno o un super admin puede ver la tanda.
    Responde 404 (no 403) para no revelar qué tandas existen.
    """
    if can_manage(tanda, user):
        return
    if await count_user_slots(db, tanda.id, user.id) == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tanda no encontrada"
        )


def ensure_organizer(tanda: Tanda, user: User, detail: str) -> None:
    if not can_manage(tanda, user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def ensure_superuser(user: User) -> None:
    if not user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo para el administrador")
