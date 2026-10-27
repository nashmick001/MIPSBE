"""FastAPI entrypoint. `/health` must answer without credentials."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
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
    role: str
    content: str


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


@app.post("/v1/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> dict:
    if not body.customer_token and not body.guest_id:
        raise HTTPException(status_code=400, detail="Provide customer_token or guest_id.")
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
