"""Transcribe endpoint: shape, auth, and error mapping (backend mocked)."""

import asyncio
import os
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import transcribe_audio


def test_transcribe_audio_posts_multipart():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["ctype"] = request.headers.get("Content-Type", "")
        seen["body"] = request.content.decode("latin1")
        return httpx.Response(200, json={"transcript": "  nataka unga "})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await transcribe_audio(main_mod.load_settings(), "a.webm", b"RIFF...", "audio/webm", client)

    with patch.dict(os.environ, {"META_API_BASE": "https://meta.test/v1", "META_API_KEY": "k", "META_VOICE_MODEL": "v"}, clear=True):
        text = asyncio.run(run())
    assert text == "nataka unga"
    assert seen["url"] == "https://meta.test/v1/asr/transcribe"
    assert seen["auth"] == "Bearer k"
    assert "multipart/form-data" in seen["ctype"]
    assert 'name="request"' in seen["body"]
    assert 'name="audio"' in seen["body"]
    assert '"audioEncoding": "WAV"' in seen["body"]


def test_transcribe_endpoint_needs_credentials():
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(main_mod.app, raise_server_exceptions=False)
        response = client.post("/v1/transcribe", files={"audio": ("a.webm", b"x", "audio/webm")})
    assert response.status_code == 503


def test_transcribe_endpoint_rejects_empty():
    env = {"META_API_KEY": "k", "META_AGENT_MODEL": "m", "DROPMTAANI_API_BASE": "b",
           "DROPMTAANI_SERVICE_TOKEN": "t", "META_VOICE_MODEL": "v"}
    with patch.dict(os.environ, env, clear=True):
        client = TestClient(main_mod.app, raise_server_exceptions=False)
        response = client.post("/v1/transcribe", files={"audio": ("a.webm", b"", "audio/webm")})
    assert response.status_code == 400
