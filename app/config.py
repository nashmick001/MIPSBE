"""Agent configuration. Secrets come from the environment only (see .env.example).

`load_settings()` never fails on missing keys so `/health` stays up on a bare
checkout. Call `require_provider_settings()` at agent startup for the strict
version that refuses to run chat without credentials.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    meta_api_base: str
    meta_api_key: str
    agent_model: str
    voice_model: str
    vision_model: str
    baseten_api_key: str
    baseten_model: str
    dropmtaani_api_base: str
    dropmtaani_service_token: str
    daily_spend_cap_usd: float
    env: str


def load_settings() -> Settings:
    """Read settings from the environment. Missing values become empty strings."""
    return Settings(
        meta_api_base=os.environ.get("META_API_BASE", "https://api.meta.ai/v1").strip(),
        meta_api_key=os.environ.get("META_API_KEY", "").strip(),
        agent_model=os.environ.get("META_AGENT_MODEL", "").strip(),
        voice_model=os.environ.get("META_VOICE_MODEL", "").strip(),
        vision_model=os.environ.get("META_VISION_MODEL", "").strip(),
        baseten_api_key=os.environ.get("BASETEN_API_KEY", "").strip(),
        baseten_model=os.environ.get("BASETEN_MODEL", "").strip(),
        dropmtaani_api_base=os.environ.get("DROPMTAANI_API_BASE", "").strip(),
        dropmtaani_service_token=os.environ.get("DROPMTAANI_SERVICE_TOKEN", "").strip(),
        daily_spend_cap_usd=float(os.environ.get("AGENT_DAILY_SPEND_CAP_USD", "20") or 20),
        env=os.environ.get("AGENT_ENV", "dev").strip(),
    )


def require_provider_settings(settings: Settings) -> Settings:
    """Strict validation for agent startup. Raises on the first missing key."""
    missing = [
        name
        for name in ("meta_api_key", "agent_model", "dropmtaani_api_base", "dropmtaani_service_token")
        if not getattr(settings, name)
    ]
    if missing:
        raise RuntimeError(f"Missing required agent settings: {', '.join(missing)} (see .env.example)")
    return settings
