from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, Response, status
from fastapi.middleware.cors import CORSMiddleware
from app.core.config import settings
from app.db.session import engine
from app.models import Base
from app.api.v1.router import api_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # En desarrollo inicial, crea las tablas si no existen en Supabase
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    # Limpieza al apagar la app
    await engine.dispose()


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="API Backend para gestión y administración comunitaria de Tandas (FastAPI + Supabase PostgreSQL)",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Configuración de CORS para Flutter y Web
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Conectar routers v1
app.include_router(api_router, prefix=settings.API_V1_STR)


@app.api_route("/", methods=["GET", "HEAD"], tags=["Health"])
async def root():
    return {
        "status": "online",
        "app": settings.PROJECT_NAME,
        "environment": settings.ENVIRONMENT,
        "docs": "/docs",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.api_route("/health", methods=["GET", "HEAD"], tags=["Health"])
@app.api_route("/ping", methods=["GET", "HEAD"], tags=["Health"])
async def health_check():
    """
    Endpoint ultra-rápido diseñado para UptimeRobot / health checks.
    Soporta peticiones GET y HEAD devolviendo HTTP 200 OK inmediatamente.
    """
    return {
        "status": "healthy",
        "ping": "pong",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
