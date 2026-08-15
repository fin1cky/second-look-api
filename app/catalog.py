"""Shopify Global Catalog client via the UCP MCP interface.

The REST catalog search (discover.shopifyapps.com) sits behind Cloudflare
bot-protection that blocks datacenter/cloud egress IPs (confirmed: identical
requests succeed from a residential IP and are hard-blocked from Modal), so
this uses Shopify's MCP-based Global Catalog tool instead. It's keyless: any
caller that presents a UCP agent profile URL (a small public JSON manifest
declaring which catalog capabilities it wants) can search, no OAuth token
needed. See https://shopify.dev/docs/agents/catalog/global-catalog.
"""

import statistics

import httpx
from fastapi import HTTPException

from app.schemas import Product

MCP_URL = "https://catalog.shopify.com/api/ucp/mcp"

# Publicly hosted by this same service at GET /ucp-agent-profile.json.
AGENT_PROFILE_URL = "https://fin1cky--second-look-api-fastapi-app.modal.run/ucp-agent-profile.json"

AGENT_PROFILE = {
    "ucp": {
        "version": "2026-04-08",
        "services": {
            "dev.ucp.shopping": [
                {
                    "version": "2026-04-08",
                    "spec": "https://ucp.dev/2026-04-08/specification/overview",
                    "transport": "mcp",
                    "schema": "https://ucp.dev/2026-04-08/services/shopping/mcp.openrpc.json",
                }
            ]
        },
        "capabilities": {
            "dev.ucp.shopping.catalog.search": [{"version": "2026-04-08"}],
            "dev.shopify.catalog.global": [{"version": "2026-04-08"}],
        },
        "payment_handlers": {},
    }
}

_http = httpx.Client(timeout=15.0)


def _search_catalog(query: str, limit: int = 4, max_price: float | None = None) -> list[dict]:
    catalog_filters = {"ships_to": {"country": "US"}}
    if max_price is not None:
        catalog_filters["price"] = {"max": round(max_price * 100)}

    body = {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "id": 1,
        "params": {
            "name": "search_catalog",
            "arguments": {
                "meta": {"ucp-agent": {"profile": AGENT_PROFILE_URL}},
                "catalog": {
                    "query": query,
                    "filters": catalog_filters,
                    "pagination": {"limit": limit},
                },
            },
        },
    }

    response = _http.post(MCP_URL, json=body)
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"Shopify Catalog MCP error {response.status_code}: {response.text}",
        )

    data = response.json()
    if "error" in data:
        raise HTTPException(status_code=502, detail=f"Shopify Catalog MCP error: {data['error']}")

    return data["result"]["structuredContent"].get("products", [])


def _best_variant(item: dict) -> dict | None:
    """Pick the cheapest in-stock variant to represent this product's listing."""
    variants = item.get("variants") or []
    candidates = [v for v in variants if v.get("availability", {}).get("available")] or variants
    if not candidates:
        return None
    return min(candidates, key=lambda v: v.get("price", {}).get("amount", float("inf")))


def _brand(item: dict, variant: dict) -> str:
    # Global Catalog has no dedicated brand field; fall back to the selling shop's name.
    for attr in item.get("metadata", {}).get("attributes") or []:
        if attr.get("name", "").lower() in ("brand", "vendor", "manufacturer"):
            values = attr.get("values") or []
            if values:
                return values[0]
    return variant.get("seller", {}).get("name", "")


def _image_url(item: dict, variant: dict) -> str:
    media = variant.get("media") or item.get("media") or []
    return media[0]["url"] if media else ""


def _is_secondhand(item: dict, variant: dict) -> bool:
    condition = variant.get("condition") or item.get("condition") or []
    return "secondhand" in condition


def _to_product(item: dict, variant: dict) -> Product:
    price = variant.get("price") or {}
    return Product(
        title=item.get("title", ""),
        brand=_brand(item, variant),
        price=price.get("amount", 0) / 100,
        currency=price.get("currency", "USD"),
        image_url=_image_url(item, variant),
        product_url=variant.get("url", ""),
        shop_name=variant.get("seller", {}).get("name", ""),
        is_secondhand=_is_secondhand(item, variant),
        upid=item.get("id", ""),
    )


def _search(query: str, limit: int = 4, max_price: float | None = None) -> list[Product]:
    products = []
    for item in _search_catalog(query, limit=limit, max_price=max_price):
        variant = _best_variant(item)
        if variant is not None:
            products.append(_to_product(item, variant))
    return products


def match_products(query: str) -> tuple[list[Product], list[Product]]:
    primary = _search(query, limit=4)
    if not primary:
        return [], []

    median_price = statistics.median(p.price for p in primary)
    budget = _search(query, limit=4, max_price=median_price * 0.5)
    return primary, budget
