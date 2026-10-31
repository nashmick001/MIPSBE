"""Photo-read endpoint: vision payload shape and validation (backend mocked)."""

import asyncio
import json
import os
from unittest.mock import patch

import httpx

import app.main as main_mod
from app.main import read_photo


def run_read(content: bytes = b"\xff\xd8fake", ctype: str = "image/jpeg"):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["payload"] = json.loads(request.content.decode())
        return httpx.Response(200, json={"choices": [{"message": {"content": "  - unga 2kg\n"}}]})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await read_photo(main_mod.load_settings(), content, ctype, client)

    env = {"META_API_BASE": "https://meta.test/v1", "META_API_KEY": "k", "META_AGENT_MODEL": "m"}
    with patch.dict(os.environ, env, clear=True):
        return asyncio.run(run()), seen


def test_read_photo_posts_image_url_part():
    text, seen = run_read()
    assert text == "- unga 2kg"
    assert seen["url"] == "https://meta.test/v1/chat/completions"
    payload = seen["payload"]
    assert payload["reasoning_effort"] == "low"
    parts = payload["messages"][0]["content"]
    images = [p for p in parts if p.get("type") == "image_url"]
    assert len(images) == 1
    assert images[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert any("shopping list" in (p.get("text") or "") for p in parts if p.get("type") == "text")


def test_read_photo_refusal_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"error": "bad image"})

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await read_photo(main_mod.load_settings(), b"xx", "image/png", client)

    env = {"META_API_BASE": "https://meta.test/v1", "META_API_KEY": "k", "META_AGENT_MODEL": "m"}
    with patch.dict(os.environ, env, clear=True):
        try:
            asyncio.run(run())
        except main_mod.PhotoReadError:
            return
    raise AssertionError("expected PhotoReadError")
