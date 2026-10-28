"""FastAPI entrypoint. `/health` must answer without credentials."""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal

import httpx
import json
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.agent.loop import run_turn
from app.agent.meta import MetaClient
from app.config import load_settings, require_provider_settings
from app.tools.dropmtaani import CustomerContext, DropMtaaniClient

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

# Browsers may only call this from the storefront; the mobile apps send no Origin header.
# AGENT_ALLOWED_ORIGINS is a comma list, e.g. "https://dropmtaani.com". Unset = no cross-origin access.
_origins = [o.strip() for o in os.environ.get("AGENT_ALLOWED_ORIGINS", "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["POST", "GET"], allow_headers=["Content-Type"])

# Every chat turn and every voice note is a paid model call, so cap how often one caller may make them.
# In-memory and per process: fine for one worker; use a shared store if this ever runs on several.
RATE_LIMIT = int(os.environ.get("AGENT_RATE_PER_MINUTE", "12") or 12)
MAX_AUDIO_BYTES = 5 * 1024 * 1024
_hits: dict[str, deque] = defaultdict(deque)


def check_rate(key: str, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    q = _hits[key]
    while q and now - q[0] > 60:
        q.popleft()
    if len(q) >= RATE_LIMIT:
        raise HTTPException(status_code=429, detail="Too many requests - slow down.")
    q.append(now)


def caller_key(request: Request, identity: str | None = None) -> str:
    ip = (request.headers.get("x-forwarded-for") or (request.client.host if request.client else "")).split(",")[0].strip()
    return f"{identity or ''}|{ip}"


@app.get("/health")
def health() -> dict:
    settings = load_settings()
    return {
        "status": "ok",
        "service": "dropmtaani-agent",
        "env": settings.env,
        "baseline": "2026-10-27",
    }


class ChatTurn(BaseModel):
    # Only user/assistant: a caller must not be able to inject a "system" or "tool" turn into the prompt.
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)
    customer_token: str | None = None
    guest_id: str | None = None
    module_id: int | None = None
    zone_ids: list[int] = Field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None


class ChatResponse(BaseModel):
    reply: str
    trace: list[dict]
    history: list[ChatTurn]


def build_clients() -> tuple[MetaClient, DropMtaaniClient]:
    try:
        settings = require_provider_settings(load_settings())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return (
        MetaClient(settings.meta_api_base, settings.meta_api_key, settings.agent_model),
        DropMtaaniClient(settings.dropmtaani_api_base, settings.dropmtaani_service_token),
    )


class TranscribeResponse(BaseModel):
    text: str


class TranscriptionError(RuntimeError):
    """The transcription backend refused or failed the audio."""


async def transcribe_audio(settings, filename: str, content: bytes, content_type: str, client: httpx.AsyncClient) -> str:
    """POST audio to Muse Voice Transcribe. Verified live: request+audio parts, WAV encoding."""
    response = await client.post(
        f"{settings.meta_api_base}/asr/transcribe",
        headers={"Authorization": f"Bearer {settings.meta_api_key}"},
        files={
            "request": (None, json.dumps({"model": settings.voice_model, "audioEncoding": "WAV"}), "application/json"),
            "audio": (filename, content, content_type),
        },
    )
    if response.status_code >= 400:
        raise TranscriptionError("Transcription service refused the audio.")
    body = response.json()
    return ((body.get("transcript") or "").strip() if isinstance(body, dict) else "")


@app.post("/v1/transcribe", response_model=TranscribeResponse)
async def transcribe(request: Request, audio: UploadFile = File(...)) -> dict:
    check_rate(caller_key(request))
    try:
        settings = require_provider_settings(load_settings())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not settings.voice_model:
        raise HTTPException(status_code=503, detail="META_VOICE_MODEL is not set (see .env.example).")
    content = await audio.read(MAX_AUDIO_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Empty audio upload.")
    if len(content) > MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Audio is too large (5 MB max).")
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            text = await transcribe_audio(
                settings, audio.filename or "audio.webm", content,
                audio.content_type or "audio/webm", client,
            )
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Transcription service unreachable: {exc}") from exc
    except TranscriptionError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"text": text}


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(body: ChatRequest, request: Request) -> dict:
    if not body.customer_token and not body.guest_id:
        raise HTTPException(status_code=400, detail="Provide customer_token or guest_id.")
    check_rate(caller_key(request, body.customer_token or body.guest_id))
    meta, client = build_clients()
    ctx = CustomerContext(
        customer_token=body.customer_token,
        guest_id=body.guest_id,
        module_id=body.module_id,
        zone_ids=body.zone_ids,
        latitude=body.latitude,
        longitude=body.longitude,
    )
    return await run_turn(body.message, [t.model_dump() for t in body.history], ctx, meta, client)
