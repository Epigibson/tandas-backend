from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_
from app.db.session import get_db
from uuid import UUID
from app.api.deps import get_current_user
from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.user import User
from app.schemas.user import UserCreate, UserResponse
from app.schemas.auth import (
    Token,
    LoginRequest,
    DeviceRegisterRequest,
    DeviceRegisterResponse,
    DeviceLoginRequest,
    PasswordResetRequest,
)
from app.services import credentials_service

router = APIRouter()


@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
async def register(user_in: UserCreate, db: AsyncSession = Depends(get_db)):
    # Verificar si el teléfono o correo ya existen
    stmt = select(User).where(
        or_(
            User.phone == user_in.phone,
            User.email == user_in.email if user_in.email else False
        )
    )
    result = await db.execute(stmt)
    existing_user = result.scalar_one_or_none()
    
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un usuario registrado con este teléfono o correo."
        )

    user = User(
        phone=user_in.phone,
        email=user_in.email,
        full_name=user_in.full_name,
        hashed_password=get_password_hash(user_in.password),
        clabe=user_in.clabe,
        bank_name=user_in.bank_name,
        avatar_url=user_in.avatar_url,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token, token_type="bearer", user=UserResponse.model_validate(user))


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    # Permite login con teléfono o email en el campo 'username'
    stmt = select(User).where(
        or_(
            User.phone == form_data.username,
            User.email == form_data.username
        )
    )
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas (teléfono/correo o contraseña inválidos)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )

    # Rehash dynamically to 10 rounds if using legacy 12 rounds (drastically speeds up login on shared CPU)
    if user.hashed_password.startswith("$2b$12$") or user.hashed_password.startswith("$2a$12$"):
        user.hashed_password = get_password_hash(form_data.password)
        db.add(user)
        await db.commit()

    token = create_access_token(subject=str(user.id))
    return Token(access_token=token, token_type="bearer", user=UserResponse.model_validate(user))


def _token_for(user: User) -> Token:
    return Token(
        access_token=create_access_token(subject=str(user.id)),
        token_type="bearer",
        user=UserResponse.model_validate(user),
    )


@router.post("/devices", response_model=DeviceRegisterResponse, status_code=status.HTTP_201_CREATED)
async def register_device(
    payload: DeviceRegisterRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Activa "Entrar con huella" en un teléfono. El secreto se entrega una sola vez;
    el teléfono lo guarda en su almacenamiento seguro y aquí solo queda su hash.
    """
    credential, secret = await credentials_service.create_device_credential(db, current_user, payload.device_name)
    return DeviceRegisterResponse(device_id=credential.id, device_secret=secret)


@router.post("/device-login", response_model=Token)
async def device_login(payload: DeviceLoginRequest, db: AsyncSession = Depends(get_db)):
    """Inicio de sesión con la llave del teléfono (la app la libera solo tras validar la huella)."""
    user = await credentials_service.authenticate_device(db, payload.device_id, payload.device_secret)
    return _token_for(user)


@router.delete("/devices/{device_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_device(
    device_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    await credentials_service.revoke_device_credential(db, device_id, current_user.id)


@router.post("/reset-password", response_model=Token)
async def reset_password(payload: PasswordResetRequest, db: AsyncSession = Depends(get_db)):
    """
    Cambia la contraseña con el código que generó el organizador de una tanda
    y deja la sesión iniciada. Revoca la huella de todos los teléfonos del usuario.
    """
    user = await credentials_service.reset_password_with_code(
        db, payload.phone_or_email, payload.code, payload.new_password
    )
    return _token_for(user)
