"""Health endpoint stays up with zero credentials configured."""

import os
from unittest.mock import patch

from fastapi.testclient import TestClient


def test_health_without_credentials():
    with patch.dict(os.environ, {}, clear=True):
        from app.main import app

        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
