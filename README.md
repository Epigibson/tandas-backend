# 🚀 TandaApp Backend (FastAPI + Supabase PostgreSQL)

Backend modular y asíncrono para la gestión y administración de tandas familiares y de amigos.

## 🛠️ Tecnologías
- **Framework:** FastAPI
- **Base de Datos:** PostgreSQL en Supabase (Session Pooler)
- **ORM / Driver:** SQLAlchemy 2.0 (Async) + `asyncpg`
- **Gestor de Paquetes:** `uv` (Ultra rápido)
- **Seguridad:** JWT (HS256) + Hashing con Bcrypt
- **Serialización:** Pydantic v2

---

## ⚙️ Configuración Rápida

1. Edita el archivo `.env` en la raíz de `backend/`:
```env
# Reemplaza TU_CONTRASEÑA_AQUI con la clave de tu proyecto en Supabase:
DATABASE_URL="postgresql+asyncpg://postgres.zpweeprqdlbbzbesvqrk:TU_CONTRASEÑA_AQUI@aws-1-us-west-2.pooler.supabase.com:5432/postgres"
```

2. Ejecuta el servidor de desarrollo:
```bash
uv run uvicorn app.main:app --reload --port 8000
```

3. Abre en tu navegador la documentación interactiva Swagger:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## 📂 Estructura de Módulos
- `app/models/`: Modelos relacionales de base de datos (`User`, `Tanda`, `TandaSlot`, `TandaRound`, `Payment`, `ActivityAuditLog`).
- `app/schemas/`: Esquemas de validación y serialización de Pydantic v2.
- `app/services/`: Lógica de negocio (algoritmo de sorteo, generación de turnos por frecuencia, verificación de pagos).
- `app/api/v1/endpoints/`:
  - `/auth`: Registro y login con JWT (teléfono o correo).
  - `/users`: Perfil y puntaje de reputación/puntualidad (*TandaScore*).
  - `/tandas`: Creación, listado, unión por código de invitación y sorteo digital.
  - `/slots`: Asignación manual de turnos y confirmación de recepción del pozo.
  - `/payments`: Envío de comprobantes y flujo de revisión (aprobar/rechazar) del organizador.
