import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse, AdminUserUpdate
from app.schemas.auth import ResetCodeResponse
from app.services.credentials_service import create_reset_code
from app.services.tanda_access import ensure_superuser

logger = logging.getLogger(__name__)

router = APIRouter()


async def get_superuser(current_user: User = Depends(get_current_user)) -> User:
    ensure_superuser(current_user)
    return current_user


async def _get_user(db: AsyncSession, user_id: UUID) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user


@router.get("/users", response_model=List[UserResponse])
async def search_users(
    q: str = "",
    admin: User = Depends(get_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Busca personas por nombre, teléfono o correo (máximo 50)."""
    stmt = select(User).order_by(User.full_name).limit(50)
    term = q.strip()
    if term:
        like = f"%{term}%"
        stmt = stmt.where(or_(User.full_name.ilike(like), User.phone.ilike(like), User.email.ilike(like)))
    return (await db.execute(stmt)).scalars().all()


@router.patch("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_in: AdminUserUpdate,
    admin: User = Depends(get_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Corrige los datos de un familiar que no sabe hacerlo desde la app."""
    user = await _get_user(db, user_id)
    changes = user_in.model_dump(exclude_unset=True)

    for field, label in (("phone", "teléfono"), ("email", "correo")):
        value = changes.get(field)
        if value is not None and value != getattr(user, field):
            taken = (await db.execute(
                select(User.id).where(getattr(User, field) == value, User.id != user.id)
            )).scalar_one_or_none()
            if taken:
                raise HTTPException(status_code=400, detail=f"Ese {label} ya lo usa otra cuenta")
    if "phone" in changes and changes["phone"] is None:
        raise HTTPException(status_code=400, detail="El teléfono no puede quedar vacío")
    if "full_name" in changes and changes["full_name"] is None:
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío")

    for field, value in changes.items():
        setattr(user, field, value)
    await db.commit()
    await db.refresh(user)
    logger.info("Admin %s editó los datos del usuario %s: %s", admin.id, user.id, sorted(changes))
    return user


@router.post("/users/{user_id}/reset-code", response_model=ResetCodeResponse)
async def create_user_reset_code(
    user_id: UUID,
    admin: User = Depends(get_superuser),
    db: AsyncSession = Depends(get_db)
):
    """Código temporal para que cualquier persona cambie su contraseña, esté o no en una tanda."""
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Para cambiar tu propia contraseña no necesitas un código")
    await _get_user(db, user_id)
    code, expires_at = await create_reset_code(db, user_id, admin.id)
    await db.commit()
    logger.info("Admin %s generó un código de contraseña para %s", admin.id, user_id)
    return ResetCodeResponse(code=code, expires_at=expires_at)
