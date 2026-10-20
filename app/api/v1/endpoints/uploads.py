import os
import uuid
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status
from app.api.deps import get_current_user
from app.models.user import User
from app.services import storage_service

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_RECEIPT_BYTES = 8 * 1024 * 1024
# La extensión la decide el servidor según el tipo: así nunca se sirve HTML o JS subido por alguien
ALLOWED_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
    "application/pdf": ".pdf",
}


@router.post("/receipt", status_code=status.HTTP_201_CREATED)
async def upload_receipt(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """
    Sube un comprobante de pago (SPEI o foto de recibo) y devuelve la URL accesible.
    """
    ext = ALLOWED_TYPES.get(file.content_type or "")
    if ext is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos de imagen (JPG, PNG, WebP, HEIC) o PDF."
        )

    contents = await file.read(MAX_RECEIPT_BYTES + 1)
    if len(contents) > MAX_RECEIPT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="El comprobante pesa demasiado (máximo 8 MB)."
        )

    filename = f"receipt_{uuid.uuid4().hex}{ext}"

    if storage_service.storage_enabled():
        ref = await storage_service.upload_receipt(filename, contents, file.content_type)
        return {"url": ref, "filename": filename}

    # Desarrollo local: disco (en Render se borraría en cada deploy)
    file_path = os.path.join(UPLOAD_DIR, filename)

    try:
        with open(file_path, "wb") as f:
            f.write(contents)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error al guardar el comprobante: {str(e)}"
        )

    # URL relativa accesible a través de la ruta montada
    file_url = f"/uploads/{filename}"
    return {"url": file_url, "filename": filename}
