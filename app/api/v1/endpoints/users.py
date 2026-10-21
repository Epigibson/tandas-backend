from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me", response_model=UserResponse)
async def update_me(
    user_update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    update_data = user_update.model_dump(exclude_unset=True)
    if update_data.get("full_name", "") is None:
        raise HTTPException(status_code=400, detail="El nombre no puede quedar vacío")
    email = update_data.get("email")
    if email and email != current_user.email:
        taken = (await db.execute(
            select(User.id).where(User.email == email, User.id != current_user.id)
        )).scalar_one_or_none()
        if taken:
            raise HTTPException(status_code=400, detail="Ese correo ya lo usa otra cuenta")
    for field, value in update_data.items():
        setattr(current_user, field, value)
    
    await db.commit()
    await db.refresh(current_user)
    return current_user
