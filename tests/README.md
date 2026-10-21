# Prueba de punta a punta

`e2e_flow.py` recorre el ciclo completo (crear, unirse eligiendo número, iniciar, aportar, aprobar,
cobrar, huella, recuperación de contraseña, admin y perfil) contra un backend local con una BD vacía.
`mock_storage.py` imita Supabase Storage y Realtime para no tocar producción.

```bash
cd backend
docker run -d --rm --name tandas-test-pg -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16-alpine
python3 tests/mock_storage.py 8799 &
DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:55432/postgres" \
SUPABASE_URL="http://127.0.0.1:8799" SUPABASE_SECRET_KEY="sb_secret_prueba" SECRET_KEY="clave-de-prueba" \
  .venv/bin/python -m uvicorn app.main:app --port 8765 &
STORAGE_MODE=1 python3 tests/e2e_flow.py   # termina con "Todo bien" y código 0
docker stop tandas-test-pg
```
