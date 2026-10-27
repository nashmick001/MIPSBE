"""FastAPI entrypoint. `/health` must answer without credentials."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import load_settings, require_provider_settings

log = logging.getLogger("dropmtaani-agent")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        require_provider_settings(load_settings())
        log.info("provider settings present")
    except RuntimeError as exc:
        log.warning("starting without provider credentials: %s", exc)
    yield


app = FastAPI(title="DropMtaani Agent", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    settings = load_settings()
    return {
        "status": "ok",
        "service": "dropmtaani-agent",
        "env": settings.env,
        "baseline": "2026-10-27",
    }
