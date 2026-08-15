"""Serper.dev Google Shopping provider: second /match product source.

Runs alongside the Shopify storefront providers (app/storefronts.py) and
merges into the same ranked pool before tiering, so the same LLM rerank pass
covers both sources.

Serper's free tier is a 2,500-query total budget for the whole project, so
results are cached in memory per query string (a repeated search never
re-hits Serper) and this is called at most once per /match request, never
in a loop or per-tier. Feature-flagged via SHOPPING_PROVIDER_ENABLED (any
value other than "false"/"0" counts as on) so it can be killed in one step.

Any failure here (bad key, timeout, network error, over quota) returns an
empty list — /match must keep working on Shopify results alone.
"""

import os
import re
import threading

import httpx

from app.schemas import Product

SERPER_URL = "https://google.serper.dev/shopping"
TIMEOUT_SECONDS = 5.0

_http = httpx.Client(timeout=TIMEOUT_SECONDS)
_cache: dict[str, list[Product]] = {}
_cache_lock = threading.Lock()


def _enabled() -> bool:
    return os.environ.get("SHOPPING_PROVIDER_ENABLED", "true").lower() not in ("false", "0")


def _parse_price(raw: str | None) -> float:
    if not raw:
        return 0.0
    match = re.search(r"[\d,]+\.?\d*", raw)
    return float(match.group(0).replace(",", "")) if match else 0.0


def _to_product(item: dict, position: int) -> Product:
    site = item.get("source", "")
    return Product(
        title=item.get("title", ""),
        brand=site,
        price=_parse_price(item.get("price")),
        currency="USD",
        image_url=item.get("imageUrl", ""),
        product_url=item.get("link", ""),
        shop_name=site,
        is_secondhand=False,
        upid=f"shopping:{item.get('link') or position}",
        relevance_score=max(0.0, 1.0 - position * 0.05),
        source="shopping",
    )


def search(query: str) -> list[Product]:
    """Normalized Google Shopping results for query, or [] on any failure."""
    if not _enabled() or not query:
        return []

    key = query.strip().lower()
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    try:
        response = _http.post(
            SERPER_URL,
            json={"q": query},
            headers={"X-API-KEY": os.environ["SERPER_API_KEY"], "Content-Type": "application/json"},
        )
        response.raise_for_status()
        items = response.json().get("shopping", [])
        products = [_to_product(item, i) for i, item in enumerate(items)]
    except Exception:
        products = []

    with _cache_lock:
        _cache[key] = products
    return products
