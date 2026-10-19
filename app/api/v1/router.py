from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, tandas, slots, payments

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(users.router, prefix="/users", tags=["Usuarios"])
api_router.include_router(tandas.router, prefix="/tandas", tags=["Tandas"])
api_router.include_router(slots.router, prefix="/slots", tags=["Turnos"])
api_router.include_router(payments.router, prefix="/payments", tags=["Pagos"])
