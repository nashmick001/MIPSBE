"""Tools call the right endpoints and never let the model set prices."""

import asyncio
import json

import httpx

from app.tools.catalog import execute_tool
from app.tools.dropmtaani import CustomerContext, DropMtaaniClient

CTX = CustomerContext(guest_id="g1", module_id=2, zone_ids=[3])


def make_client(handler) -> DropMtaaniClient:
    return DropMtaaniClient(
        "https://api.test", "svc-token", transport=httpx.MockTransport(handler)
    )


def test_search_products_trims_and_hits_endpoint():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["module"] = request.headers.get("moduleId")
        seen["zone"] = request.headers.get("zoneId")
        seen["auth"] = request.headers.get("Authorization")
        products = [
            {"id": i, "name": f"item{i}", "price": 10, "store_id": 7,
             "store_name": "s", "image_full_url": "u", "junk": "x"}
            for i in range(12)
        ]
        return httpx.Response(200, json={"products": products, "total_size": 12})

    result = asyncio.run(execute_tool("search_products", {"query": "unga"}, CTX, make_client(handler)))
    assert seen["url"] == "https://api.test/api/v1/items/search?name=unga"
    assert seen["module"] == "2"
    assert seen["zone"] == "[3]"
    assert seen["auth"] == "Bearer svc-token"
    assert result["total"] == 12
    assert len(result["items"]) == 8
    assert set(result["items"][0]) == {"id", "name", "price", "discount", "store_id", "store_name", "image_full_url"}


def test_add_to_cart_takes_price_from_server():
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/details/5"):
            return httpx.Response(200, json={"id": 5, "name": "Unga", "price": 250, "store_id": 7})
        posts.append(json.loads(request.content))
        return httpx.Response(200, json={"ok": True})

    result = asyncio.run(
        execute_tool("add_to_cart", {"item_id": 5, "quantity": 2}, CTX, make_client(handler))
    )
    assert result["added"]["quantity"] == 2
    assert posts[0]["price"] == 250
    assert posts[0]["store_id"] == 7
    assert posts[0]["guest_id"] == "g1"


def test_unknown_tool_is_error_dict_not_exception():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP should happen")

    result = asyncio.run(execute_tool("nope", {}, CTX, make_client(handler)))
    assert result == {"error": "unknown tool: nope"}


def test_api_error_becomes_error_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errors": []})

    result = asyncio.run(execute_tool("get_deals", {}, CTX, make_client(handler)))
    assert "error" in result
