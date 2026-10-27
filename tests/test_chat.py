"""Chat endpoint: identity required, creds required, happy path delegates."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient

import app.main as main_mod


def test_chat_needs_identity():
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(main_mod.app, raise_server_exceptions=False)
        response = client.post("/v1/chat", json={"message": "hi"})
    assert response.status_code == 400


def test_chat_needs_provider_credentials():
    with patch.dict(os.environ, {}, clear=True):
        client = TestClient(main_mod.app, raise_server_exceptions=False)
        response = client.post("/v1/chat", json={"message": "hi", "guest_id": "g1"})
    assert response.status_code == 503


def test_chat_happy_path(monkeypatch):
    async def fake_run_turn(message, history, ctx, meta, client):
        assert message == "nataka unga"
        assert ctx.guest_id == "g1"
        return {"reply": "Sawa.", "trace": [], "history": history + [
            {"role": "user", "content": message},
            {"role": "assistant", "content": "Sawa."},
        ]}

    monkeypatch.setattr(main_mod, "run_turn", fake_run_turn)
    monkeypatch.setattr(main_mod, "build_clients", lambda: (object(), object()))
    client = TestClient(main_mod.app, raise_server_exceptions=False)
    response = client.post("/v1/chat", json={"message": "nataka unga", "guest_id": "g1"})
    assert response.status_code == 200
    assert response.json()["reply"] == "Sawa."
