"""
FastAPI application entry point.

Run with:
    uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router
from app.teaching_intelligence.router import router as teaching_intelligence_router
from app.lesson_intelligence.router import router as lesson_intelligence_router
from app.utils.config import settings
from app.utils.file_utils import ensure_directory


logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Prepare runtime directories and log service lifecycle events."""
    logger.info("Starting NCERT PDF Extraction Service")
    ensure_directory(settings.temp_dir)
    ensure_directory(settings.output_dir)
    yield
    logger.info("Shutting down NCERT PDF Extraction Service")


app = FastAPI(
    title="NCERT PDF Extractor",
    description="Extract structured educational content from NCERT PDFs using MinerU.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    # Lets Vercel preview deployments through when CORS_ORIGIN_REGEX is set.
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Return JSON for unhandled errors so the CORS middleware still tags the
    response — a bare 500 has no CORS headers and reaches the browser as the
    misleading "Failed to fetch"."""
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": str(exc)})


app.include_router(router, prefix="/api")
app.include_router(teaching_intelligence_router, prefix="/teaching-intelligence")
app.include_router(teaching_intelligence_router, prefix="/phase3", include_in_schema=False)
app.include_router(lesson_intelligence_router, prefix="/lesson-intelligence")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
