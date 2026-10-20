import logging
from typing import Dict, Iterable
import httpx
from fastapi import HTTPException, status
from app.core.config import settings

logger = logging.getLogger(__name__)

RECEIPTS_BUCKET = "comprobantes"
# Así se guarda en la BD la referencia a un comprobante del bucket privado;
# la URL descargable se firma al momento de responder y caduca.
STORAGE_REF_PREFIX = f"storage://{RECEIPTS_BUCKET}/"
LOCAL_REF_PREFIX = "/uploads/receipt_"
SIGNED_URL_TTL_SECONDS = 60 * 60


def storage_enabled() -> bool:
    return bool(settings.SUPABASE_URL and settings.SUPABASE_SECRET_KEY)


def valid_receipt_prefix() -> str:
    """Prefijo que debe tener un comprobante subido por /upload/receipt en este entorno."""
    return STORAGE_REF_PREFIX if storage_enabled() else LOCAL_REF_PREFIX


def _auth_headers() -> Dict[str, str]:
    key = settings.SUPABASE_SECRET_KEY
    return {"apikey": key, "Authorization": f"Bearer {key}"}


async def upload_receipt(filename: str, contents: bytes, content_type: str) -> str:
    url = f"{settings.SUPABASE_URL}/storage/v1/object/{RECEIPTS_BUCKET}/{filename}"
    headers = {**_auth_headers(), "Content-Type": content_type, "x-upsert": "false"}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(url, content=contents, headers=headers)
    except httpx.HTTPError as e:
        logger.error("Error de red subiendo comprobante a Storage: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo guardar el comprobante")

    if res.status_code >= 300:
        logger.error("Storage rechazó el comprobante (%s): %s", res.status_code, res.text[:300])
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="No se pudo guardar el comprobante")
    return STORAGE_REF_PREFIX + filename


async def sign_receipt_refs(refs: Iterable[str]) -> Dict[str, str]:
    """
    Firma en una sola llamada las referencias storage:// y devuelve {referencia: url_firmada}.
    Si Storage falla, regresa lo que haya podido firmar para no tumbar el listado de pagos.
    """
    paths = sorted({r[len(STORAGE_REF_PREFIX):] for r in refs if r and r.startswith(STORAGE_REF_PREFIX)})
    if not paths or not storage_enabled():
        return {}

    url = f"{settings.SUPABASE_URL}/storage/v1/object/sign/{RECEIPTS_BUCKET}"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            res = await client.post(
                url,
                json={"expiresIn": SIGNED_URL_TTL_SECONDS, "paths": paths},
                headers=_auth_headers(),
            )
        res.raise_for_status()
        items = res.json()
    except (httpx.HTTPError, ValueError) as e:
        logger.error("No se pudieron firmar comprobantes: %s", e)
        return {}

    signed = {}
    for item in items:
        if item.get("error") or not item.get("signedURL"):
            continue
        signed[STORAGE_REF_PREFIX + item["path"]] = f"{settings.SUPABASE_URL}/storage/v1{item['signedURL']}"
    return signed
