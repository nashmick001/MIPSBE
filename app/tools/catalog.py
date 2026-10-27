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
            "name": "search_products",
            "description": "Search the product catalog by name. Returns matching items with ids, prices and stores.",
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
            "description": "Search stores by name.",
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
            "description": "Current cart contents and total for one store.",
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
            "description": "Add an item to the cart. Price and store are read from the server, never from the request.",
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
]


async def execute_tool(name: str, args: dict[str, Any], ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    """Run one tool call. Always returns a JSON-able dict, errors included."""
    try:
        if name == "search_products":
            body = await client.search_products(ctx, args["query"])
            return {"items": _trim_products(_rows(body, "products")), "total": body.get("total_size")}
        if name == "search_stores":
            body = await client.search_stores(ctx, args["query"])
            return {"stores": [_pick(r, ["id", "name"]) for r in _rows(body, "stores")[:MAX_ROWS]]}
        if name == "get_categories":
            body = await client.categories(ctx, args.get("search"))
            return {"categories": [_pick(r, ["id", "name"]) for r in _rows(body, "categories")[:MAX_ROWS]]}
        if name == "get_popular":
            body = await client.popular_items(ctx)
            return {"items": _trim_products(_rows(body, "products"))}
        if name == "get_deals":
            body = await client.discounted_items(ctx)
            return {"items": _trim_products(_rows(body, "products"))}
        if name == "get_item":
            body = await client.item_details(ctx, int(args["item_id"]))
            item = body.get("product") if isinstance(body.get("product"), dict) else body
            out = _pick(item, ["id", "name", "price", "store_id", "store_name", "variations"])
            out["model"] = "ItemCampaign" if item.get("campaign") else "Item"
            return {"item": out}
        if name == "get_cart":
            return _trim_cart(await client.cart_list(ctx, int(args["store_id"])))
        if name == "add_to_cart":
            return await _add_to_cart(args, ctx, client)
        if name == "update_cart":
            return await _update_cart(args, ctx, client)
        if name == "remove_from_cart":
            await client.cart_remove(ctx, int(args["cart_id"]), int(args["store_id"]))
            return {"removed": int(args["cart_id"])}
        return {"error": f"unknown tool: {name}"}
    except (DropMtaaniError, KeyError, ValueError, TypeError) as exc:
        return {"error": str(exc)[:300]}


async def _add_to_cart(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    details = await client.item_details(ctx, int(args["item_id"]))
    item = details.get("product") if isinstance(details.get("product"), dict) else details
    if not item.get("id"):
        return {"error": "item not found"}
    await client.cart_add(
        ctx,
        item_id=int(item["id"]),
        model="ItemCampaign" if item.get("campaign") else "Item",
        price=float(item["price"]),
        quantity=max(1, int(args["quantity"])),
        store_id=int(item["store_id"]),
    )
    return {"added": {"item_id": item["id"], "name": item.get("name"), "quantity": int(args["quantity"])}}


async def _update_cart(args: dict, ctx: CustomerContext, client: DropMtaaniClient) -> dict:
    cart = _trim_cart(await client.cart_list(ctx, int(args["store_id"])))
    row = next(
        (r for r in cart["items"] if r.get("id") == args["cart_id"] or r.get("cart_id") == args["cart_id"]),
        None,
    )
    if row is None:
        return {"error": "cart row not found — call get_cart first"}
    await client.cart_update(
        ctx,
        cart_id=int(args["cart_id"]),
        price=float(row["price"]),
        quantity=max(1, int(args["quantity"])),
        store_id=int(args["store_id"]),
    )
    return {"updated": {"cart_id": args["cart_id"], "quantity": int(args["quantity"])}}
