"""Centralized application settings loaded from environment or .env."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import field_validator
from pydantic_settings import BaseSettings

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"


class Settings(BaseSettings):
    """Application configuration loaded from environment or .env."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = True

    # CORS
    frontend_url: str = "http://localhost:3000"
    # Extra allowed origins, comma-separated (e.g. the production Vercel domain).
    cors_origins: str = ""
    # Regex for dynamic origins such as Vercel preview deployments,
    # e.g. https://.*\.vercel\.app
    cors_origin_regex: str = ""

    # Paths
    temp_dir: str = "./tmp/ncert"
    output_dir: str = "./output"

    # Background extraction jobs. MinerU loads several GB of models per run,
    # so concurrent extractions are the fastest way to OOM a small droplet.
    max_concurrent_extractions: int = 1
    # LLM jobs are network-bound rather than memory-bound, so a few can overlap;
    # the cap exists to stay inside DeepSeek rate limits.
    max_concurrent_llm_jobs: int = 4

    @property
    def allowed_origins(self) -> list[str]:
        """Deduplicated CORS allow-list: frontend_url + extras + local dev."""
        candidates = [
            self.frontend_url,
            *self.cors_origins.split(","),
            "http://localhost:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:3001",
        ]
        cleaned = [origin.strip().rstrip("/") for origin in candidates]
        return list(dict.fromkeys(origin for origin in cleaned if origin))

    # MinerU CPU pipeline
    mineru_backend: str = "pipeline"
    mineru_method: str = "auto"
    mineru_lang: str = "auto"
    mineru_server_url: str = ""
    mineru_formula: bool = True
    mineru_table: bool = True
    mineru_image_analysis: bool = False
    mineru_cpu_threads: int = 0
    mineru_timeout_seconds: int = 3600
    mineru_quality_mode: str = "max"
    mineru_ocr_fallback: bool = True

    # DeepSeek semantic intelligence
    semantic_intelligence_prompt_version: int | None = None
    phase2_prompt_version: int | None = None
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"

    # Phase 3 — Teaching Intelligence
    phase3_prompt_version: int = 1
    phase3_default_style: str = "engaging"

    # Supabase persistence
    supabase_url: str = ""
    supabase_service_key: str = ""
    
    # MariaDB
    mariadb_host: str = "127.0.0.1"
    mariadb_port: int = 3306
    mariadb_user: str = "root"
    mariadb_password: str = ""
    mariadb_db: str = "pdf_extraction"

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug_mode(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"dev", "development"}:
                return True
        return value

    class Config:
        env_file = str(_ENV_FILE) if _ENV_FILE.is_file() else ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
