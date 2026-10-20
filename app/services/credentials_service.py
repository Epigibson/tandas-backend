import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID
from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.config import settings
from app.core.security import get_password_hash
from app.models.credentials import DeviceCredential, PasswordResetCode
from app.models.user import User

RESET_CODE_TTL = timedelta(minutes=30)
RESET_CODE_MAX_ATTEMPTS = 5
# Sin 0/O, 1/I/L: el código se dicta o se manda por WhatsApp
RESET_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
RESET_CODE_LENGTH = 8


def _keyed_hash(value: str) -> str:
    """HMAC con SECRET_KEY: aunque se filtre la tabla, no se pueden probar códigos sin la llave del servidor."""
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _normalize_code(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


# ---------------------------------------------------------------------------
# Llaves de dispositivo (Entrar con huella)
# ---------------------------------------------------------------------------

async def create_device_credential(db: AsyncSession, user: User, device_name: str) -> tuple[DeviceCredential, str]:
    secret = secrets.token_urlsafe(32)
    credential = DeviceCredential(
        user_id=user.id,
        secret_hash=_keyed_hash(secret),
        device_name=device_name.strip()[:100] or "Teléfono",
    )
    db.add(credential)
    await db.commit()
    return credential, secret


async def authenticate_device(db: AsyncSession, device_id: UUID, secret: str) -> User:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="La huella ya no es válida en este teléfono. Entra con tu contraseña.",
    )
    credential = (await db.execute(
        select(DeviceCredential).where(DeviceCredential.id == device_id)
    )).scalar_one_or_none()
    if not credential or credential.revoked_at is not None:
        raise invalid
    if not hmac.compare_digest(credential.secret_hash, _keyed_hash(secret)):
        raise invalid

    user = (await db.execute(select(User).where(User.id == credential.user_id))).scalar_one_or_none()
    if not user or not user.is_active:
        raise invalid

    credential.last_used_at = datetime.now(timezone.utc)
    await db.commit()
    return user


async def revoke_device_credential(db: AsyncSession, device_id: UUID, user_id: UUID) -> None:
    credential = (await db.execute(
        select(DeviceCredential).where(DeviceCredential.id == device_id, DeviceCredential.user_id == user_id)
    )).scalar_one_or_none()
    if credential and credential.revoked_at is None:
        credential.revoked_at = datetime.now(timezone.utc)
        await db.commit()


async def _revoke_all_devices(db: AsyncSession, user_id: UUID) -> None:
    await db.execute(
        update(DeviceCredential)
        .where(DeviceCredential.user_id == user_id, DeviceCredential.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


# ---------------------------------------------------------------------------
# Códigos para restablecer contraseña
# ---------------------------------------------------------------------------

async def create_reset_code(db: AsyncSession, target_user_id: UUID, created_by: UUID) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    # Solo un código vivo por persona: generar uno nuevo anula los anteriores
    await db.execute(
        update(PasswordResetCode)
        .where(PasswordResetCode.user_id == target_user_id, PasswordResetCode.used_at.is_(None))
        .values(used_at=now)
    )
    raw = "".join(secrets.choice(RESET_CODE_ALPHABET) for _ in range(RESET_CODE_LENGTH))
    expires_at = now + RESET_CODE_TTL
    db.add(PasswordResetCode(
        user_id=target_user_id,
        created_by_user_id=created_by,
        code_hash=_keyed_hash(raw),
        expires_at=expires_at,
    ))
    await db.commit()
    return f"{raw[:4]}-{raw[4:]}", expires_at


async def reset_password_with_code(db: AsyncSession, phone_or_email: str, code: str, new_password: str) -> User:
    # Mismo mensaje para usuario inexistente, código equivocado o vencido: no revela quién existe
    invalid = HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="El código no es válido o ya venció. Pídele uno nuevo al organizador de tu tanda.",
    )
    identifier = phone_or_email.strip()
    user = (await db.execute(
        select(User).where((User.phone == identifier) | (User.email == identifier))
    )).scalar_one_or_none()
    if not user:
        raise invalid

    now = datetime.now(timezone.utc)
    reset = (await db.execute(
        select(PasswordResetCode)
        .where(
            PasswordResetCode.user_id == user.id,
            PasswordResetCode.used_at.is_(None),
            PasswordResetCode.expires_at > now,
        )
        .order_by(PasswordResetCode.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if not reset:
        raise invalid

    if not hmac.compare_digest(reset.code_hash, _keyed_hash(_normalize_code(code))):
        reset.failed_attempts += 1
        if reset.failed_attempts >= RESET_CODE_MAX_ATTEMPTS:
            reset.used_at = now  # se quema tras demasiados intentos
        await db.commit()
        raise invalid

    user.hashed_password = get_password_hash(new_password)
    reset.used_at = now
    # Si alguien más tenía acceso, la huella de otros teléfonos deja de servir
    await _revoke_all_devices(db, user.id)
    await db.commit()
    return user
