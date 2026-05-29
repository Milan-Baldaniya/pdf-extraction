"""Optional Supabase client factory."""

from __future__ import annotations

import logging
from typing import Any

from app.utils.config import settings

logger = logging.getLogger(__name__)

try:
    from supabase import Client, create_client
except ImportError:
    Client = Any  # type: ignore[assignment]
    create_client = None


def _create_supabase_client() -> Any | None:
    if create_client is None:
        logger.warning("Supabase package is not installed.")
        return None
    if not settings.supabase_url or not settings.supabase_service_key:
        logger.warning("Supabase URL/service key is not configured.")
        return None
    try:
        return create_client(settings.supabase_url, settings.supabase_service_key)
    except Exception as exc:
        logger.warning("Failed to create Supabase client: %s", exc)
        return None


supabase: Any | None = _create_supabase_client()
