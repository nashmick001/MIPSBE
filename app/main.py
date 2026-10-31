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
from app.demo_links import store as demo_store
from app.tools.dropmtaani import CustomerContext, DropMtaaniClient

log = logging.getLogger("dropmtaani-agent")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        require_provider_settings(load_settings())
        log.info("provider settings present")
    except RuntimeError as exc:
        log.warning("starting without provider credentials: %s", exc)
    seed = os.environ.get("DEMO_MAGIC_SEED", "")
    if seed and ":" in seed:
        email, _, persona = seed.partition(":")
        demo_store.mint(email.strip(), persona.strip() or None)
        log.info("seeded a sample demo link for %s", email.strip())
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
MAX_PHOTO_BYTES = 4 * 1024 * 1024
PHOTO_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
NOTHING_VISIBLE = "NO_FOOD_VISIBLE"

PHOTO_READ_PROMPT = (
    "This photo is the customer's shopping list or the inside of their fridge. "
    "Read it carefully and reply ONLY with lines in this shape, one item per line: "
    '"- name — qty/notes". Rules: transcribe list entries verbatim (brand + size when '
    "shown); for a fridge, name each visible food item and obvious empties "
    '("milk — nearly empty"); mark anything illegible as "unclear — <best guess?>" '
    "instead of inventing; ignore non-food clutter; no chatter, no headers, just the lines. "
    "If no food or list is visible at all, reply exactly: NO_FOOD_VISIBLE"
)
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


class PhotoReadResponse(BaseModel):
    items_text: str
    visible: bool


class PhotoReadError(RuntimeError):
    """The vision backend refused or failed the photo."""


async def read_photo(settings, content: bytes, content_type: str, client: httpx.AsyncClient) -> str:
    """Read a shopping list / fridge photo with Muse vision. Verified live:
    image_url part on chat/completions, reasoning low, 2000-token budget."""
    import base64

    data_url = "data:" + content_type + ";base64," + base64.b64encode(content).decode()
    response = await client.post(
        f"{settings.meta_api_base}/chat/completions",
        headers={"Authorization": f"Bearer {settings.meta_api_key}"},
        json={
            "model": settings.vision_model or settings.agent_model,
            "max_tokens": 2000,
            "reasoning_effort": "low",
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": PHOTO_READ_PROMPT},
                {"type": "image_url", "image_url": {"url": data_url}},
            ]}],
        },
    )
    if response.status_code >= 400:
        raise PhotoReadError("Vision service refused the photo.")
    body = response.json()
    try:
        return (body["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise PhotoReadError("Vision service returned no read.") from exc


@app.post("/v1/photo-read", response_model=PhotoReadResponse)
async def photo_read(request: Request, image: UploadFile = File(...)) -> dict:
    """Sample of the panel's photo turn: read the list/fridge photo, return
    item lines the agent turns into an order suggestion."""
    check_rate(caller_key(request))
    try:
        settings = require_provider_settings(load_settings())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if image.content_type not in PHOTO_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Photo must be JPEG, PNG or WebP.")
    content = await image.read(MAX_PHOTO_BYTES + 1)
    if not content:
        raise HTTPException(status_code=400, detail="Empty photo upload.")
    if len(content) > MAX_PHOTO_BYTES:
        raise HTTPException(status_code=413, detail="Photo is too large (4 MB max).")
    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            text = await read_photo(settings, content, image.content_type or "image/jpeg", client)
    except PhotoReadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Vision backend unreachable: {exc}") from exc
    return {"items_text": text, "visible": text != NOTHING_VISIBLE}


class DemoMagicRequest(BaseModel):
    # No min_length: any token-shaped value gets a 403 verdict from verify(),
    # mirroring the panel (the storefront bounces home on a 422).
    token: str = Field(max_length=200)


class DemoMagicResponse(BaseModel):
    token: str
    is_demo: bool = True
    login_type: str = "demo"
    email: str


@app.post("/v1/auth/demo-magic", response_model=DemoMagicResponse)
def demo_magic(body: DemoMagicRequest, request: Request) -> dict:
    """Sample of POST /api/v1/auth/demo-magic on the panel: a judge link
    token trades for a demo session. Wrong in any way is a 403, never a 422,
    so the storefront shows the error instead of bouncing home. On the panel
    the Passport session is capped to die with the link, and revoking ends
    open sessions too (the sample keeps no sessions)."""
    check_rate(caller_key(request))
    link = demo_store.verify(body.token)
    if link is None:
        raise HTTPException(status_code=403, detail="That demo link is invalid, expired or revoked.")
    return {"token": f"sample-session-{link.id}", "email": link.email}


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
