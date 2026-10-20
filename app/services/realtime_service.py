import asyncio
import logging
from typing import Set
from uuid import UUID
import httpx
from app.core.config import settings

logger = logging.getLogger(__name__)

TANDA_CHANGED_EVENT = "changed"
# Referencias a los envíos en curso: sin ellas el recolector de basura puede cancelar la tarea
_pending: Set[asyncio.Task] = set()


def tanda_topic(tanda_id: UUID) -> str:
    return f"tanda:{tanda_id}"


def notify_tanda_changed(tanda_id: UUID) -> None:
    """
    Avisa por Supabase Realtime (Broadcast) que la tanda cambió, sin esperar la respuesta.
    El aviso no lleva datos sensibles: la app solo vuelve a pedir el detalle al backend,
    que sigue validando que quien pregunta sea miembro.
    """
    if not (settings.SUPABASE_URL and settings.SUPABASE_SECRET_KEY):
        return
    task = asyncio.create_task(_send(tanda_id))
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _send(tanda_id: UUID) -> None:
    key = settings.SUPABASE_SECRET_KEY
    body = {
        "messages": [{
            "topic": tanda_topic(tanda_id),
            "event": TANDA_CHANGED_EVENT,
            "payload": {"tanda_id": str(tanda_id)},
        }]
    }
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            res = await client.post(
                f"{settings.SUPABASE_URL}/realtime/v1/api/broadcast",
                json=body,
                headers={"apikey": key, "Authorization": f"Bearer {key}"},
            )
        if res.status_code >= 300:
            logger.warning("Realtime rechazó el aviso de la tanda %s (%s): %s", tanda_id, res.status_code, res.text[:200])
    except httpx.HTTPError as e:
        # Si falla, la app igual se puede refrescar jalando hacia abajo
        logger.warning("No se pudo avisar el cambio de la tanda %s: %s", tanda_id, e)
