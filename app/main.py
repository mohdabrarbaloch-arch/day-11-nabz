"""Nabz — precision oncology workspace. Application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import get_settings
from .database import init_db
from .deps import build_limiters, rate_limit_dependency
from .routers import auth, matching, patients

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nabz")

STATIC_DIR = Path(__file__).parent / "static"

general_limiter, login_limiter = build_limiters()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_db()
    logger.info("Database ready (%s)", settings.database_url.split("://")[0])
    if settings.seed_on_startup:
        from .seed import seed_if_empty

        created = seed_if_empty()
        if created:
            logger.info("Seeded demo data: %s", created)
    yield


app = FastAPI(
    title="Nabz",
    description=(
        "A precision-oncology workspace: clinical profiles, molecular findings, "
        "and a transparent biomarker-to-therapy matcher. Research and portfolio "
        "software — not a medical device."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Helmet-equivalent headers, without pulling in a dependency."""
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if settings.is_production:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Never leak a stack trace to the client."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "An internal error occurred. It has been logged."},
    )


app.include_router(auth.router, dependencies=[Depends(rate_limit_dependency(general_limiter))])
app.include_router(patients.router, dependencies=[Depends(rate_limit_dependency(general_limiter))])
app.include_router(matching.router, dependencies=[Depends(rate_limit_dependency(general_limiter))])


@app.get("/api/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "nabz", "version": "1.0.0"}


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
