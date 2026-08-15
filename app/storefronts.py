"""Fallback product source: direct per-store Shopify storefront /products.json.

Shopify's centralized Catalog API (app/catalog.py) is unreachable from Modal:
Cloudflare bot-protection blocks Modal's egress IP on both the REST
(discover.shopifyapps.com) and MCP (catalog.shopify.com) endpoints, confirmed
by the identical request succeeding from a residential IP and being
hard-blocked from Modal on every retry. Every Shopify storefront's own
/products.json is public, needs no auth, and is reachable from Modal, so this
ranks products across a curated list of real stores instead.

This is a stand-in for true cross-merchant catalog search: relevance comes
from keyword overlap against a fixed store list, not Shopify's own search
ranking, and every listing here is new (single-brand storefronts don't carry
secondhand inventory) unlike the aggregated global catalog.
"""

import re
import statistics
import threading

import httpx

from app.schemas import Product

STORES = [
    {"domain": "allbirds.com", "shop_name": "Allbirds"},
    {"domain": "rothys.com", "shop_name": "Rothy's"},
    {"domain": "taylorstitch.com", "shop_name": "Taylor Stitch"},
    {"domain": "parachutehome.com", "shop_name": "Parachute"},
    {"domain": "brooklinen.com", "shop_name": "Brooklinen"},
    {"domain": "gymshark.com", "shop_name": "Gymshark"},
    {"domain": "chubbiesshorts.com", "shop_name": "Chubbies"},
    {"domain": "beginningboutique.com", "shop_name": "Beginning Boutique"},
    {"domain": "puravidabracelets.com", "shop_name": "Pura Vida Bracelets"},
    {"domain": "bando.com", "shop_name": "ban.do"},
]

PRODUCTS_PER_STORE = 250
_WORD_RE = re.compile(r"[a-z0-9]+")

_http = httpx.Client(timeout=15.0)
_cache: list[dict] | None = None
_cache_lock = threading.Lock()


def _fetch_store(store: dict) -> list[dict]:
    response = _http.get(
        f"https://{store['domain']}/products.json",
        params={"limit": PRODUCTS_PER_STORE},
    )
    response.raise_for_status()
    products = response.json().get("products", [])
    for product in products:
        product["_store"] = store
    return products


def _get_all_products() -> list[dict]:
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                fetched = []
                for store in STORES:
                    try:
                        fetched.extend(_fetch_store(store))
                    except httpx.HTTPError:
                        continue
                _cache = fetched
    return _cache


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def _tags_text(tags) -> str:
    return tags if isinstance(tags, str) else " ".join(tags or [])


def _relevance_score(query_tokens: set[str], product: dict) -> float:
    if not query_tokens:
        return 0.0
    product_text = " ".join(
        [product.get("title", ""), product.get("product_type", ""), _tags_text(product.get("tags"))]
    )
    overlap = query_tokens & _tokenize(product_text)
    return len(overlap) / len(query_tokens)


def _best_variant(product: dict) -> dict | None:
    """Pick the cheapest in-stock variant to represent this product's listing."""
    variants = product.get("variants") or []
    candidates = [v for v in variants if v.get("available")] or variants
    if not candidates:
        return None
    return min(candidates, key=lambda v: float(v.get("price") or "inf"))


def _to_product(product: dict, variant: dict, relevance_score: float) -> Product:
    store = product["_store"]
    images = product.get("images") or []
    return Product(
        title=product.get("title", ""),
        brand=product.get("vendor") or store["shop_name"],
        price=float(variant.get("price") or 0),
        currency="USD",
        image_url=images[0]["src"] if images else "",
        product_url=f"https://{store['domain']}/products/{product.get('handle', '')}",
        shop_name=store["shop_name"],
        is_secondhand=False,
        upid=f"{store['domain']}:{product.get('id')}",
        relevance_score=round(relevance_score, 4),
    )


def _rank(search_query: str, category: str, color: str, material: str) -> list[Product]:
    query_tokens = _tokenize(" ".join([search_query, category, color, material]))

    scored = []
    for product in _get_all_products():
        score = _relevance_score(query_tokens, product)
        if score <= 0:
            continue
        variant = _best_variant(product)
        if variant is not None:
            scored.append(_to_product(product, variant, score))

    return sorted(scored, key=lambda p: p.relevance_score, reverse=True)


def match_products(
    search_query: str, category: str, color: str, material: str
) -> tuple[list[Product], list[Product], list[Product]]:
    ranked = _rank(search_query, category, color, material)

    primary = ranked[:4]
    if not primary:
        return [], [], []

    used_upids = {p.upid for p in primary}
    remaining = [p for p in ranked if p.upid not in used_upids]
    median_price = statistics.median(p.price for p in primary)

    mid = [p for p in remaining if median_price * 0.5 <= p.price <= median_price][:4]
    used_upids |= {p.upid for p in mid}
    remaining = [p for p in remaining if p.upid not in used_upids]

    budget = [p for p in remaining if p.price < median_price * 0.5][:4]
    if not budget:
        budget = sorted(remaining, key=lambda p: p.price)[:4]

    return primary, mid, budget
