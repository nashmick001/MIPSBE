"""Sample magic-link login: mint/verify semantics + the endpoint contract."""

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app import main
from app.demo_links import DemoLinkStore


def fresh_store(monkeypatch) -> DemoLinkStore:
    store = DemoLinkStore()
    monkeypatch.setattr(main, "demo_store", store)
    return store


def test_mint_verify_roundtrip():
    store = DemoLinkStore()
    link, plain = store.mint("judge@demo.test", "foodie")
    assert link.is_live()
    assert store.verify(plain) is link
    assert link.last_used_at is not None


def test_plaintext_never_stored():
    store = DemoLinkStore()
    _, plain = store.mint("judge@demo.test")
    assert all(link.token_hash != plain for link in store.links.values())


def test_unknown_token_rejected():
    assert DemoLinkStore().verify("x" * 48) is None


def test_expired_and_revoked_rejected():
    store = DemoLinkStore()
    _, plain = store.mint("judge@demo.test", days=20)
    future = datetime.now(timezone.utc) + timedelta(days=21)
    assert store.verify(plain, future) is None
    assert store.revoke("judge@demo.test") == 1
    assert store.verify(plain) is None


def test_mint_revokes_older_links():
    store = DemoLinkStore()
    _, first = store.mint("judge@demo.test")
    _, second = store.mint("judge@demo.test")
    assert store.verify(first) is None
    assert store.verify(second) is not None


def test_endpoint_exchanges_and_refuses(monkeypatch):
    store = fresh_store(monkeypatch)
    _, plain = store.mint("judge@demo.test", "foodie")
    client = TestClient(main.app)
    ok = client.post("/v1/auth/demo-magic", json={"token": plain})
    assert ok.status_code == 200
    assert ok.json()["is_demo"] is True
    assert ok.json()["login_type"] == "demo"
    bad = client.post("/v1/auth/demo-magic", json={"token": "z" * 48})
    assert bad.status_code == 403
    assert bad.status_code != 422
