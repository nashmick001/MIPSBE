"""Tools fan out across shopping sections and write to the item's own section."""

import asyncio
import json

import httpx

from app.tools.catalog import execute_tool
from app.tools.dropmtaani import CustomerContext, DropMtaaniClient

CTX = CustomerContext(guest_id="g1", module_id=4, zone_ids=[2])

MODULES = [
    {"id": 4, "module_name": "Food", "module_type": "food"},
    {"id": 6, "module_name": "SHOP", "module_type": "ecommerce"},
    {"id": 7, "module_name": "Parcel", "module_type": "parcel"},
]


def make_client(handler) -> DropMtaaniClient:
    return DropMtaaniClient(
        "https://api.test", "svc-token", transport=httpx.MockTransport(handler)
    )


def module_router(handler):
    """Serve /module from MODULES, route everything else to handler."""

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/module":
            assert request.url.params["zone_id"] == "2"
            return httpx.Response(200, json=MODULES)
        return handler(request)

    return route


def test_search_fans_out_and_tags_sections():
    seen_modules = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/items/search"):
            seen_modules.append(request.headers["moduleId"])
        mid = request.headers["moduleId"]
        return httpx.Response(200, json={
            "products": [{"id": int(mid), "name": f"item{mid}", "price": 10}],
            "total_size": 1,
        })

    result = asyncio.run(execute_tool("search_products", {"query": "unga"}, CTX, make_client(module_router(handler))))
    assert seen_modules == ["4", "6"]
    assert [(i["id"], i["module"]) for i in result["items"]] == [(4, "Food"), (6, "SHOP")]


def test_search_prefers_category_and_tags_it():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        mid = request.headers.get("moduleId")
        calls.append((path, mid))
        if path == "/api/v1/categories/":
            if mid == "6":
                return httpx.Response(200, json={"categories": [{"id": 352, "name": "Vapes"}]})
            return httpx.Response(200, json={"categories": []})
        if path == "/api/v1/categories/items/352":
            return httpx.Response(200, json={"products": [{"id": 1, "name": "Happy Bar", "price": 500}]})
        return httpx.Response(200, json={"products": [{"id": 9, "name": "Fumakilla Vape Mat", "price": 100}]})

    result = asyncio.run(execute_tool("search_products", {"query": "vape"}, CTX, make_client(module_router(handler))))
    assert result["categories"] == [{"id": 352, "name": "Vapes", "module": "SHOP"}]
    by_module = {i["module"]: i for i in result["items"]}
    assert by_module["SHOP"]["match"] == 'category "Vapes"'
    assert by_module["SHOP"]["id"] == 1
    assert "match" not in by_module["Food"]
    assert ("/api/v1/items/search", "6") not in calls


def test_search_caps_three_per_module():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "products": [{"id": i, "name": f"n{i}", "price": 1} for i in range(10)],
            "total_size": 10,
        })

    result = asyncio.run(execute_tool("search_products", {"query": "x"}, CTX, make_client(module_router(handler))))
    assert len(result["items"]) == 6


def test_service_token_plus_customer_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["customer"] = request.headers.get("X-Customer-Token")
        return httpx.Response(200, json={"products": [], "total_size": 0})

    ctx = CustomerContext(customer_token="cust-1", guest_id="g1", module_id=4, zone_ids=[2])
    asyncio.run(execute_tool("search_products", {"query": "x"}, ctx, make_client(module_router(handler))))
    assert seen["auth"] == "Bearer svc-token"
    assert seen["customer"] == "cust-1"


def test_passthrough_without_service_token():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("Authorization")
        seen["customer"] = request.headers.get("X-Customer-Token")
        return httpx.Response(200, json={"products": [], "total_size": 0})

    client = DropMtaaniClient("https://api.test", "", transport=httpx.MockTransport(handler))
    ctx = CustomerContext(customer_token="cust-1", module_id=4, zone_ids=[2])
    asyncio.run(client.search_products(ctx, "x"))
    assert seen["auth"] == "Bearer cust-1"
    assert seen["customer"] is None


def test_search_falls_back_to_caller_module():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/module":
            return httpx.Response(500, json={})
        if request.url.path.endswith("/items/search"):
            seen.append(request.headers["moduleId"])
        return httpx.Response(200, json={"products": [], "total_size": 0})

    result = asyncio.run(execute_tool("search_products", {"query": "x"}, CTX, make_client(handler)))
    assert seen == ["4"]
    assert result == {"items": []}


def test_add_to_cart_uses_item_module_and_server_price():
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/module":
            return httpx.Response(200, json=MODULES)
        if request.url.path.endswith("/details/5"):
            if request.headers["moduleId"] == "4":
                return httpx.Response(404, json={"errors": []})
            return httpx.Response(200, json={"id": 5, "name": "Unga", "price": 250, "store_id": 7, "module_id": 6})
        posts.append((request.headers["moduleId"], json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    result = asyncio.run(
        execute_tool("add_to_cart", {"item_id": 5, "quantity": 2}, CTX, make_client(handler))
    )
    assert result["added"]["quantity"] == 2
    assert posts[0][0] == "6"
    assert posts[0][1]["price"] == 250
    assert posts[0][1]["guest_id"] == "g1"


def test_get_cart_merges_sections():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/module":
            return httpx.Response(200, json=MODULES)
        if request.headers["moduleId"] == "6":
            return httpx.Response(200, json={"carts": [{"id": 9, "name": "Unga", "quantity": 1, "price": 250}], "total": 250})
        return httpx.Response(200, json={"carts": []})

    result = asyncio.run(execute_tool("get_cart", {"store_id": 7}, CTX, make_client(handler)))
    assert result == {"carts": [{"module": "SHOP", "items": result["carts"][0]["items"], "total": 250}]}
    assert result["carts"][0]["items"][0]["name"] == "Unga"


def test_update_finds_row_in_other_section():
    writes = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/module":
            return httpx.Response(200, json=MODULES)
        if request.url.path.endswith("/cart/list"):
            if request.headers["moduleId"] == "6":
                return httpx.Response(200, json={"carts": [{"id": 9, "name": "U", "quantity": 1, "price": 100}]})
            return httpx.Response(200, json={"carts": []})
        writes.append((request.headers["moduleId"], json.loads(request.content)))
        return httpx.Response(200, json={"ok": True})

    result = asyncio.run(
        execute_tool("update_cart", {"cart_id": 9, "store_id": 7, "quantity": 3}, CTX, make_client(handler))
    )
    assert result == {"updated": {"cart_id": 9, "quantity": 3}}
    assert writes[0][0] == "6"
    assert writes[0][1]["price"] == 100


def test_bare_array_body_parses_via_data():
    # categories/ answers a top-level JSON array; the client wraps it as {"data": [...]}.

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"id": 1, "name": "Alcohol"}, {"id": 2, "name": "Bakery"}])

    result = asyncio.run(execute_tool("get_categories", {}, CTX, make_client(handler)))
    assert result == {"categories": [{"id": 1, "name": "Alcohol"}, {"id": 2, "name": "Bakery"}]}


def test_unknown_tool_is_error_dict_not_exception():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP should happen")

    result = asyncio.run(execute_tool("nope", {}, CTX, make_client(handler)))
    assert result == {"error": "unknown tool: nope"}


def test_place_order_delivery_flow():
    posts = []
    ctx = CustomerContext(customer_token="cust-1", module_id=4, zone_ids=[2])

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/module":
            return httpx.Response(200, json=MODULES)
        if path.endswith("/cart/list"):
            if request.headers["moduleId"] == "6":
                return httpx.Response(200, json={"carts": [{"id": 1, "item_id": 5, "name": "Unga", "quantity": 2, "price": 250}], "total": 500})
            return httpx.Response(200, json={"carts": []})
        if path == "/api/v1/customer/address/list":
            return httpx.Response(200, json={"addresses": [{"id": 3, "address_type": "Home", "address": "M 1", "latitude": "-0.53", "longitude": "37.65"}]})
        if path == "/api/v1/stores/details/7":
            return httpx.Response(200, json={"id": 7, "latitude": "-0.53", "longitude": "37.64"})
        if path == "/api/v1/customer/order/place":
            posts.append((request.headers["moduleId"], json.loads(request.content)))
            return httpx.Response(200, json={"order_id": 100, "total_ammount": 540, "status": "pending"})
        raise AssertionError(f"unexpected {path}")

    result = asyncio.run(execute_tool("place_order", {
        "store_id": 7, "order_type": "delivery", "address_id": 3,
        "payment_method": "digital_payment", "confirm_total": 500, "coupon_code": None,
    }, ctx, make_client(handler)))
    assert result == {"order": {"id": 100, "total": 540, "status": "pending"}}
    assert posts[0][0] == "6"
    assert posts[0][1]["store_id"] == 7
    assert posts[0][1]["distance"] > 0
    assert posts[0][1]["address"] == "M 1"


def test_place_order_refuses_stale_total():
    placed = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/module":
            return httpx.Response(200, json=MODULES)
        if path.endswith("/cart/list"):
            return httpx.Response(200, json={"carts": [{"id": 1, "name": "U", "quantity": 1, "price": 100}]})
        if path == "/api/v1/customer/order/place":
            placed.append(True)
        return httpx.Response(200, json={"carts": []})

    ctx = CustomerContext(customer_token="cust-1", module_id=4, zone_ids=[2])
    result = asyncio.run(execute_tool("place_order", {
        "store_id": 7, "order_type": "delivery", "address_id": 3,
        "payment_method": "digital_payment", "confirm_total": 1,
    }, ctx, make_client(handler)))
    assert "changed" in result["error"]
    assert placed == []


def test_place_order_guests_cannot():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("no HTTP should happen")

    result = asyncio.run(execute_tool("place_order", {
        "store_id": 7, "order_type": "delivery", "address_id": 3,
        "payment_method": "digital_payment", "confirm_total": 1,
    }, CTX, make_client(handler)))
    assert "logged-in" in result["error"]


def test_get_orders_list_and_track():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/v1/customer/order/list":
            return httpx.Response(200, json={"orders": [{"id": 55, "order_status": "handover", "payment_status": "paid", "order_amount": 540}]})
        if path == "/api/v1/customer/order/track":
            assert request.url.params["order_id"] == "55"
            return httpx.Response(200, json={
                "id": 55, "order_status": "handover", "payment_status": "paid",
                "payment_method": "digital_payment", "order_amount": 540,
                "delivery_address": {"address": "M 1"},
                "delivery_man": {"f_name": "J", "l_name": "K"},
            })
        raise AssertionError(f"unexpected {path}")

    ctx = CustomerContext(customer_token="cust-1", module_id=4, zone_ids=[2])
    listed = asyncio.run(execute_tool("get_orders", {}, ctx, make_client(handler)))
    assert listed == {"orders": [{"id": 55, "order_status": "handover", "payment_status": "paid", "order_amount": 540}]}
    tracked = asyncio.run(execute_tool("get_orders", {"order_id": 55}, ctx, make_client(handler)))
    assert tracked["order"]["rider"] == "J K"
    assert tracked["order"]["deliver_to"] == "M 1"


def test_get_addresses():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"addresses": [{"id": 3, "address_type": "Home", "address": "M 1"}]})

    ctx = CustomerContext(customer_token="cust-1", module_id=4, zone_ids=[2])
    result = asyncio.run(execute_tool("get_addresses", {}, ctx, make_client(handler)))
    assert result == {"addresses": [{"id": 3, "address_type": "Home", "address": "M 1"}]}


def test_api_error_becomes_error_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"errors": []})

    result = asyncio.run(execute_tool("get_deals", {}, CTX, make_client(handler)))
    assert "error" in result
