import os
import uuid
from fastapi import APIRouter, UploadFile, File, HTTPException, status
from fastapi.responses import JSONResponse

router = APIRouter()

UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@router.post("/receipt", status_code=status.HTTP_201_CREATED)
async def upload_receipt(file: UploadFile = File(...)):
    """
    Sube un comprobante de pago (SPEI o foto de recibo) y devuelve la URL accesible.
    """
    if not file.content_type.startswith("image/") and file.content_type != "application/pdf":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se permiten archivos de imagen (JPG, PNG, WebP) o PDF."
        )

    ext = os.path.splitext(file.filename)[1] or ".jpg"
    filename = f"receipt_{uuid.uuid4().hex[:12]}{ext}"
    file_path = os.path.join(UPLOAD_DIR, filename)

    try:
        contents = await file.read()
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
