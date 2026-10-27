"""HTTP client for the real DropMtaani API.

Uses the scoped service token only. Endpoint methods land with openapi.yaml;
this file carries the shared plumbing (auth headers, timeouts, errors).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import httpx


class DropMtaaniError(RuntimeError):
    """Any non-2xx answer or transport failure from the DropMtaani API."""


@dataclass(frozen=True)
class CustomerContext:
    """Who and where the request is for. Identity: customer token, else guest id."""

    customer_token: str | None = None
    guest_id: str | None = None
    module_id: int | None = None
    zone_ids: list = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None


class DropMtaaniClient:
    def __init__(
        self,
        base_url: str,
        service_token: str,
        timeout: float = 15.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._timeout = timeout
        self._transport = transport

    def _headers(self, ctx: CustomerContext) -> dict:
        token = ctx.customer_token or self._service_token
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        if ctx.module_id:
            headers["moduleId"] = str(ctx.module_id)
        if ctx.zone_ids:
            headers["zoneId"] = json.dumps(list(ctx.zone_ids))
        if ctx.latitude is not None:
            headers["latitude"] = str(ctx.latitude)
        if ctx.longitude is not None:
            headers["longitude"] = str(ctx.longitude)
        return headers

    async def _request(self, method: str, path: str, ctx: CustomerContext, **kwargs) -> dict:
        url = f"{self._base_url}/{path.lstrip('/')}"
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
                response = await client.request(method, url, headers=self._headers(ctx), **kwargs)
        except httpx.HTTPError as exc:
            raise DropMtaaniError(f"DropMtaani API unreachable: {exc}") from exc
        if response.status_code >= 400:
            raise DropMtaaniError(f"DropMtaani API {response.status_code} on {method} {path}")
        body = response.json()
        return body if isinstance(body, dict) else {"data": body}

    def _guest(self, ctx: CustomerContext) -> dict:
        if ctx.customer_token or not ctx.guest_id:
            return {}
        return {"guest_id": ctx.guest_id}

    # -- catalog (paths per openapi.yaml) ------------------------------------

    async def search_products(self, ctx: CustomerContext, name: str) -> dict:
        return await self._request("GET", "api/v1/items/search", ctx, params={"name": name})

    async def search_stores(self, ctx: CustomerContext, name: str) -> dict:
        return await self._request("GET", "api/v1/stores/search", ctx, params={"name": name})

    async def categories(self, ctx: CustomerContext, search: str | None = None) -> dict:
        params = {"search": search} if search else {}
        return await self._request("GET", "api/v1/categories/", ctx, params=params)

    async def popular_items(self, ctx: CustomerContext) -> dict:
        return await self._request("GET", "api/v1/items/popular", ctx)

    async def discounted_items(self, ctx: CustomerContext) -> dict:
        return await self._request("GET", "api/v1/items/discounted", ctx)

    async def item_details(self, ctx: CustomerContext, item_id: int) -> dict:
        return await self._request("GET", f"api/v1/items/details/{item_id}", ctx)

    # -- cart -----------------------------------------------------------------

    async def cart_list(self, ctx: CustomerContext, store_id: int) -> dict:
        return await self._request(
            "GET", "api/v1/customer/cart/list", ctx,
            params={"store_id": store_id, **self._guest(ctx)},
        )

    async def cart_add(
        self, ctx: CustomerContext, item_id: int, model: str, price: float,
        quantity: int, store_id: int, variation: list | None = None,
    ) -> dict:
        return await self._request(
            "POST", "api/v1/customer/cart/add", ctx,
            json={
                "item_id": item_id, "model": model, "price": price,
                "quantity": quantity, "store_id": store_id,
                "variation": variation or [], **self._guest(ctx),
            },
        )

    async def cart_update(
        self, ctx: CustomerContext, cart_id: int, price: float, quantity: int, store_id: int,
    ) -> dict:
        return await self._request(
            "POST", "api/v1/customer/cart/update", ctx,
            json={
                "cart_id": cart_id, "price": price,
                "quantity": quantity, "store_id": store_id, **self._guest(ctx),
            },
        )

    async def cart_remove(self, ctx: CustomerContext, cart_id: int, store_id: int) -> dict:
        return await self._request(
            "DELETE", "api/v1/customer/cart/remove-item", ctx,
            json={"cart_id": cart_id, "store_id": store_id, **self._guest(ctx)},
        )
