"""Parity tool set: everything the old chatbot could do, over the real API.

Two rules shape every tool here:
1. The model never sets prices. add/update take ids + quantities; price and
   store always come from a server read first. A "set price to 0" prompt has
   nowhere to land — there is no price argument.
2. Results are trimmed to what the model needs (8 rows max). The reasoning
   model charges per token, so full catalog rows never reach it.
"""

from __future__ import annotations

from typing import Any

from app.tools.dropmtaani import CustomerContext, DropMtaaniClient, DropMtaaniError

MAX_ROWS = 8
PER_MODULE_ROWS = 3

# Module types with searchable product catalogs. Parcel, rental, ride-share
# and service have no item search, so fan-out skips them.
SHOPPING_TYPES = {"food", "grocery", "pharmacy", "ecommerce"}


async def _shopping_modules(ctx: CustomerContext, client: DropMtaaniClient) -> list:
    """Active shopping modules, or the caller's module alone as fallback."""
    try:
        body = await client.modules(ctx)
        rows = _rows(body, "modules", "data")
        found = [
            {"id": r["id"], "name": r.get("module_name") or r.get("name") or str(r["id"])}
            for r in rows
            if isinstance(r, dict) and r.get("id") and r.get("module_type") in SHOPPING_TYPES
        ]
        if found:
            return found
    except DropMtaaniError:
        pass
    if ctx.module_id:
        return [{"id": ctx.module_id, "name": "current section"}]
    return []


def _rows(body: dict, *keys: str) -> list:
    for key in keys:
        value = body.get(key)
        if isinstance(value, list):
            return value
    return []


def _pick(row: dict, fields: list[str]) -> dict:
    return {f: row.get(f) for f in fields}


def _trim_products(rows: list) -> list:
    return [
        _pick(r, ["id", "name", "price", "discount", "store_id", "store_name", "image_full_url"])
        for r in rows[:MAX_ROWS]
        if isinstance(r, dict)
    ]


def _trim_cart(body: dict) -> dict:
    rows = _rows(body, "carts", "cart", "data")
    if not rows and isinstance(body.get("data"), dict):
        rows = _rows(body["data"], "carts", "cart")
    return {
        "items": [
            _pick(r, ["id", "cart_id", "item_id", "name", "quantity", "price"])
            for r in rows[:MAX_ROWS]
            if isinstance(r, dict)
        ],
        "total": body.get("total") or (body.get("data") or {}).get("total") if isinstance(body.get("data"), dict) else body.get("total"),
    }


TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_modules",
            "description": "Shopping sections (Food, Grocery, Pharmacy, SHOP). Call once when unsure where to look.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_products",
            "description": "Search products across ALL shopping sections. Resolves the query against category names first, then item names. Category hits carry a match tag naming the category.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_stores",
            "description": "Search stores by name across ALL shopping sections.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_categories",
            "description": "List shopping categories, optionally filtered by a search word.",
            "parameters": {
                "type": "object",
                "properties": {"search": {"type": "string"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_popular",
            "description": "Popular items right now.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_deals",
            "description": "Discounted items (deals).",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_item",
            "description": "Full details of one item: price, store, variations. Call before adding to cart when unsure.",
            "parameters": {
                "type": "object",
                "properties": {"item_id": {"type": "integer"}},
                "required": ["item_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_cart",
            "description": "Current cart for one store, from whichever section it lives in.",
            "parameters": {
                "type": "object",
                "properties": {"store_id": {"type": "integer"}},
                "required": ["store_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_to_cart",
            "description": "Add an item to its own section's cart, wherever the customer is chatting from. Price and store are read from the server, never from the request.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "quantity": {"type": "integer", "minimum": 1},
                },
                "required": ["item_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_cart",
            "description": "Change the quantity of a cart row.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cart_id": {"type": "integer"},
                    "store_id": {"type": "integer"},
                    "quantity": {"type": "integer", "minimum": 1},
                },
                "required": ["cart_id", "store_id", "quantity"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_from_cart",
            "description": "Remove one row from the cart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cart_id": {"type": "integer"},
                    "store_id": {"type": "integer"},
                },
                "required": ["cart_id", "store_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_addresses",
            "description": "Saved delivery addresses with their IDs, so the customer can pick one for a delivery order.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "place_order",
            "description": "Place an order for ONE store bucket. Only after showing the recap and getting an explicit yes: pass the exact quoted subtotal as confirm_total — refuses when the cart changed. Delivery needs a saved address_id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "store_id": {"type": "integer"},
                    "order_type": {"type": "string", "enum": ["delivery", "take_away"]},
                    "address_id": {"type": ["integer", "null"]},
                    "payment_method": {
                        "type": "string",
                        "enum": ["cash_on_delivery", "digital_payment", "wallet"],
                    },
                    "confirm_total": {"type": "number"},
                    "coupon_code": {"type": ["string", "null"]},
                },
                "required": ["store_id", "order_type", "payment_method", "confirm_total"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_orders",
            "description": "Recent orders with live status, or one order's tracking detail. Guests pass their contact_number for tracking.",
            "parameters": {
                "type": "object",
                "properties": {
                    "order_id": {"type": ["integer", "null"]},
                    "contact_number": {"type": ["string", "null"]},
                },
            },
        },
    },
]


async def execute_tool(name: str, args: dict[str, Any], ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    """Run one tool call. Always returns a JSON-able dict, errors included."""
    try:
        if name == "get_modules":
            return {"modules": await _shopping_modules(ctx, client)}
        if name == "search_products":
            return await _search_all("products", args["query"], ctx, client)
        if name == "search_stores":
            return await _search_all("stores", args["query"], ctx, client)
        if name == "get_categories":
            body = await client.categories(ctx, args.get("search"))
            return {"categories": [_pick(r, ["id", "name"]) for r in _rows(body, "categories", "data")[:MAX_ROWS]]}
        if name == "get_popular":
            body = await client.popular_items(ctx)
            return {"items": _trim_products(_rows(body, "products", "data"))}
        if name == "get_deals":
            body = await client.discounted_items(ctx)
            return {"items": _trim_products(_rows(body, "products", "data"))}
        if name == "get_item":
            item, _ = await _details_any_module(int(args["item_id"]), ctx, client)
            if not item.get("id"):
                return {"error": "item not found in any section"}
            out = _pick(item, ["id", "name", "price", "store_id", "store_name", "variations"])
            out["model"] = "ItemCampaign" if item.get("campaign") else "Item"
            return {"item": out}
        if name == "get_cart":
            return await _get_cart_anywhere(args, ctx, client)
        if name == "add_to_cart":
            return await _add_to_cart(args, ctx, client)
        if name == "update_cart":
            return await _update_cart(args, ctx, client)
        if name == "remove_from_cart":
            return await _remove_from_cart(args, ctx, client)
        if name == "get_addresses":
            body = await client.address_list(ctx)
            return {"addresses": [_pick(r, ["id", "address_type", "address"]) for r in _rows(body, "addresses", "data")[:MAX_ROWS]]}
        if name == "place_order":
            return await _place_order(args, ctx, client)
        if name == "get_orders":
            return await _get_orders(args, ctx, client)
        return {"error": f"unknown tool: {name}"}
    except (DropMtaaniError, KeyError, ValueError, TypeError) as exc:
        return {"error": str(exc)[:300]}


async def _search_all(kind: str, query: str, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    """Search every shopping section; tag each hit with its section name.

    Products resolve the full query against category names first (a query
    naming a category is stronger intent than a substring hit on an
    unrelated item); only sections with no category match fall back to a
    name search. Category hits carry a match tag naming the category.
    """
    out: list = []
    categories: list = []
    for module in await _shopping_modules(ctx, client):
        mctx = client.with_module(ctx, module["id"])
        match_tag = ""
        if kind == "products":
            try:
                found = _match_categories(await client.categories(mctx, query), query)
            except DropMtaaniError:
                found = []
            if found:
                categories.extend({**c, "module": module["name"]} for c in found)
                match_tag = f"category \"{found[0]['name']}\""
                try:
                    body = await client.category_items(mctx, int(found[0]["id"]))
                except DropMtaaniError:
                    continue
                rows = _rows(body, "products", "data")[:PER_MODULE_ROWS]
            else:
                try:
                    body = await client.search_products(mctx, query)
                except DropMtaaniError:
                    continue
                rows = _rows(body, "products", "data")[:PER_MODULE_ROWS]
        else:
            try:
                body = await client.search_stores(mctx, query)
            except DropMtaaniError:
                continue
            rows = _rows(body, "stores", "data")[:PER_MODULE_ROWS]
        for row in rows:
            if not isinstance(row, dict):
                continue
            hit = _pick(row, ["id", "name", "price", "discount", "store_id", "store_name", "image_full_url"])
            hit["module"] = module["name"]
            if match_tag:
                hit["match"] = match_tag
            out.append(hit)
    key = "items" if kind == "products" else "stores"
    result: dict = {key: out}
    if categories:
        result["categories"] = categories
    return result


def _match_categories(body: dict, query: str) -> list:
    """Categories whose name contains the full query (mirrors the LIKE)."""
    needle = query.strip().lower()
    if not needle:
        return []
    return [
        _pick(r, ["id", "name"])
        for r in _rows(body, "categories", "data")
        if isinstance(r, dict) and r.get("id") and needle in str(r.get("name") or "").lower()
    ]


async def _details_any_module(item_id: int, ctx: CustomerContext, client: DropMtaaniClient) -> tuple:
    """Item details + the module that answered (details are module-scoped)."""
    for module in await _shopping_modules(ctx, client):
        try:
            body = await client.item_details(client.with_module(ctx, module["id"]), item_id)
        except DropMtaaniError:
            continue
        item = body.get("product") if isinstance(body.get("product"), dict) else body
        if item.get("id"):
            return item, int(item.get("module_id") or module["id"])
    return {}, 0


async def _cart_in_modules(store_id: int, ctx: CustomerContext, client: DropMtaaniClient) -> list:
    """This store's cart rows from every section that has any: [(module, cart)]."""
    found = []
    for module in await _shopping_modules(ctx, client):
        try:
            cart = _trim_cart(await client.cart_list(client.with_module(ctx, module["id"]), store_id))
        except DropMtaaniError:
            continue
        if cart["items"]:
            found.append((module, cart))
    return found


async def _get_cart_anywhere(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    carts = [
        {"module": module["name"], "items": cart["items"], "total": cart["total"]}
        for module, cart in await _cart_in_modules(int(args["store_id"]), ctx, client)
    ]
    return {"carts": carts}


async def _add_to_cart(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    item, module_id = await _details_any_module(int(args["item_id"]), ctx, client)
    if not item.get("id"):
        return {"error": "item not found in any section"}
    mctx = client.with_module(ctx, module_id)
    await client.cart_add(
        mctx,
        item_id=int(item["id"]),
        model="ItemCampaign" if item.get("campaign") else "Item",
        price=float(item["price"]),
        quantity=max(1, int(args["quantity"])),
        store_id=int(item["store_id"]),
    )
    return {"added": {"item_id": item["id"], "name": item.get("name"), "quantity": int(args["quantity"])}}


async def _find_cart_row(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> tuple:
    """Locate a cart row across sections: (module_id, row) or (0, None)."""
    for module, cart in await _cart_in_modules(int(args["store_id"]), ctx, client):
        row = next(
            (r for r in cart["items"] if r.get("id") == args["cart_id"] or r.get("cart_id") == args["cart_id"]),
            None,
        )
        if row is not None:
            return module["id"], row
    return 0, None


async def _update_cart(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    module_id, row = await _find_cart_row(args, ctx, client)
    if row is None:
        return {"error": "cart row not found — call get_cart first"}
    await client.cart_update(
        client.with_module(ctx, module_id),
        cart_id=int(args["cart_id"]),
        price=float(row["price"]),
        quantity=max(1, int(args["quantity"])),
        store_id=int(args["store_id"]),
    )
    return {"updated": {"cart_id": args["cart_id"], "quantity": int(args["quantity"])}}


async def _remove_from_cart(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    module_id, row = await _find_cart_row(args, ctx, client)
    if row is None:
        return {"error": "cart row not found — call get_cart first"}
    await client.cart_remove(client.with_module(ctx, module_id), int(args["cart_id"]), int(args["store_id"]))
    return {"removed": int(args["cart_id"])}


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Straight-line km, the same server-side distance the checkout quote uses."""
    from math import asin, cos, radians, sin, sqrt

    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    h = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 6378.137 * 2 * asin(sqrt(h))


async def _place_order(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    """One store bucket through checkout. Guests cannot order; the quoted
    subtotal must still match or the call is refused (stale-cart guard)."""
    if not ctx.customer_token:
        return {"error": "ordering needs a logged-in customer"}
    order_type = args.get("order_type")
    if order_type not in ("delivery", "take_away"):
        return {"error": "order_type must be delivery or take_away"}
    if args.get("payment_method") not in ("cash_on_delivery", "digital_payment", "wallet"):
        return {"error": "pick a payment method first: cash_on_delivery, digital_payment or wallet"}
    if args.get("confirm_total") is None:
        return {"error": "pass the exact quoted subtotal as confirm_total"}

    store_id = int(args["store_id"])
    found = await _cart_in_modules(store_id, ctx, client)
    if not found:
        return {"error": "that store's cart bucket is empty"}
    module, cart = found[0]
    subtotal = round(sum(float(r.get("price") or 0) * int(r.get("quantity") or 0) for r in cart["items"]), 2)
    if abs(subtotal - float(args["confirm_total"])) > 0.01:
        return {"error": f"cart changed since the recap (now {subtotal}) — show the cart again first"}

    payload: dict = {
        "store_id": store_id,
        "order_type": order_type,
        "payment_method": args["payment_method"],
        "coupon_code": args.get("coupon_code"),
    }
    if order_type == "delivery":
        try:
            addresses = _rows(await client.address_list(ctx), "addresses", "data")
        except DropMtaaniError:
            return {"error": "could not read saved addresses"}
        address = next((a for a in addresses if isinstance(a, dict) and a.get("id") == args.get("address_id")), None)
        if address is None:
            return {"error": "unknown address — call get_addresses first"}
        try:
            store = await client.store_details(ctx, store_id)
        except DropMtaaniError:
            return {"error": "could not read the store"}
        try:
            distance = _haversine_km(
                float(store.get("latitude")), float(store.get("longitude")),
                float(address.get("latitude")), float(address.get("longitude")),
            )
        except (TypeError, ValueError):
            return {"error": "that address has no usable map pin"}
        payload.update({
            "address": address.get("address"),
            "latitude": address.get("latitude"),
            "longitude": address.get("longitude"),
            "distance": round(distance, 3),
        })
    else:
        if ctx.latitude is None or ctx.longitude is None:
            return {"error": "take-away still needs the customer location"}
        payload.update({"latitude": ctx.latitude, "longitude": ctx.longitude})

    try:
        body = await client.order_place(client.with_module(ctx, module["id"]), payload)
    except DropMtaaniError as exc:
        return {"error": str(exc)[:300]}
    if not body.get("order_id"):
        errors = body.get("errors") or []
        detail = errors[0].get("message") if errors and isinstance(errors[0], dict) else "checkout failed"
        return {"error": f"the store declined the order: {detail}"}
    return {"order": {
        "id": body.get("order_id"),
        "total": body.get("total_ammount"),
        "status": body.get("status"),
    }}


async def _get_orders(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    if args.get("order_id") is not None:
        try:
            body = await client.order_track(ctx, int(args["order_id"]), args.get("contact_number"))
        except DropMtaaniError:
            return {"error": "order not found on this account"}
        order = _pick(body, ["id", "order_status", "payment_status", "payment_method", "order_amount"])
        detail = body.get("delivery_address")
        if isinstance(detail, dict) and detail.get("address"):
            order["deliver_to"] = detail["address"]
        rider = body.get("delivery_man")
        if isinstance(rider, dict):
            order["rider"] = " ".join(str(rider.get(k) or "") for k in ("f_name", "l_name")).strip()
        return {"order": order}
    body = await client.order_list(ctx)
    return {"orders": [
        _pick(r, ["id", "order_status", "payment_status", "order_amount"])
        for r in _rows(body, "orders", "data")[:MAX_ROWS]
        if isinstance(r, dict)
    ]}
