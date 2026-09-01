"""Centralized application settings loaded from environment or .env."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import field_validator
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

_BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _BACKEND_ROOT / ".env"

# Mirror the .env into os.environ as well. Settings covers the declared fields,
# but the numbered Gemini key pool (GEMINI_API_KEY2..N) is read straight from
# the environment, and pydantic-settings drops undeclared names.
if _ENV_FILE.is_file():
    load_dotenv(_ENV_FILE, override=False)


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

    # LLM provider for semantic intelligence. "deepseek" or "gemini".
    # Both are driven through the OpenAI-compatible chat-completions API, so
    # switching providers needs no change in the agents or services.
    llm_provider: str = "deepseek"

    # DeepSeek semantic intelligence
    semantic_intelligence_prompt_version: int | None = None
    phase2_prompt_version: int | None = None
    deepseek_api_key: str = ""
    deepseek_model: str = "deepseek-v4-pro"

    # Gemini (via its OpenAI-compatible endpoint). Additional keys are read
    # straight from the environment as GEMINI_API_KEY2..N and rotated on 429;
    # see _provider_keys in semantic_intelligence/deepseek_client.py.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Spend guards for the semantic intelligence swarm.
    # DeepSeek v4 models are reasoning models: 60-78% of their billed output is
    # hidden chain-of-thought. One chapter cost ~765k tokens on v4-pro, so an
    # unattended queue can drain an account before anyone notices. A run that
    # crosses this ceiling aborts instead of continuing to spend.
    semantic_max_tokens_per_chapter: int = 1_500_000
    # Concurrent TOPICS in flight. Each one fires 4 agent calls covering all of
    # that topic's concepts, so 15 meant ~60 simultaneous requests; billing
    # settles on completion, which is how a balance overshoots into the negative.
    semantic_max_concurrency: int = 5
    # Most concepts one agent call may be asked for. The swarm runs per topic so
    # the ~9,000 tokens of role prompt and JSON schema are paid once per topic
    # rather than once per concept, but a topic is not allowed to be unbounded:
    # Agent 4 writes 4-6 full mark schemes PER concept, so an 11-concept topic
    # would ask for ~50 of them in one JSON reply. A reply that overruns comes
    # back unparseable, is retried three times, is billed all three times, and
    # yields nothing. Topics above this are split into consecutive batches over
    # the same slice. 8 covers all but a handful of topics in this corpus.
    semantic_max_concepts_per_call: int = 8

    @property
    def active_llm_model(self) -> str:
        """Model name of whichever provider is selected, for audit columns."""
        if (self.llm_provider or "").strip().lower() == "gemini":
            return self.gemini_model
        return self.deepseek_model

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
