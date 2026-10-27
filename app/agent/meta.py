"""Minimal async client for the Meta Model API chat endpoint.

Verified against the live API (see scripts/check_provider.py): Spark models
are reasoning-heavy, so every call sets a low reasoning effort and a generous
completion budget — otherwise the model spends the whole budget thinking and
returns empty content.
"""

from __future__ import annotations

import httpx


class MetaError(RuntimeError):
    """Transport failure or non-2xx answer from the Meta Model API."""


class MetaClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120.0,
        max_tokens: int = 2000,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        self._model = model
        self._timeout = timeout
        self._max_tokens = max_tokens

    async def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """One chat round. Returns the raw assistant message dict."""
        payload: dict = {
            "model": self._model,
            "messages": messages,
            "max_tokens": self._max_tokens,
            "reasoning_effort": "low",
        }
        if tools:
            payload["tools"] = tools
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/chat/completions",
                    headers=self._headers,
                    json=payload,
                )
        except httpx.HTTPError as exc:
            raise MetaError(f"Meta API unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise MetaError(f"Meta API {response.status_code}: {response.text[:300]}")
        body = response.json()
        try:
            return body["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise MetaError(f"Meta API returned no message: {body!r}"[:300]) from exc
