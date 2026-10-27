"""HTTP client for the real DropMtaani API.

Uses the scoped service token only. Endpoint methods land with openapi.yaml;
this file carries the shared plumbing (auth headers, timeouts, errors).
"""

from __future__ import annotations

import httpx


class DropMtaaniError(RuntimeError):
    """Any non-2xx answer or transport failure from the DropMtaani API."""


class DropMtaaniClient:
    def __init__(self, base_url: str, service_token: str, timeout: float = 15.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {service_token}",
            "Accept": "application/json",
        }
        self._timeout = timeout

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.request(method, url, headers=self._headers, **kwargs)
        except httpx.HTTPError as exc:
            raise DropMtaaniError(f"DropMtaani API unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise DropMtaaniError(f"DropMtaani API {response.status_code} on {method} {path}")
        body = response.json()
        return body if isinstance(body, dict) else {"data": body}
