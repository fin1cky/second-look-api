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
secondhand inventory) unlike the aggregated global catalog. The store list is
mainstream, broad-catalog Shopify-hosted brands rather than niche DTC labels
with a handful of SKUs, so common items (tees, hoodies, jeans, sneakers,
sunglasses) actually get hits — see the module docstring in the repo's
README for the verification process and the price/category spread.
"""

import re
import statistics
import threading

import httpx

from app.schemas import Product

STORES = [
    # basics/staples
    {"domain": "trueclassic.com", "shop_name": "True Classic"},
    {"domain": "freshcleantees.com", "shop_name": "Fresh Clean Tees"},
    {"domain": "bearbottomclothing.com", "shop_name": "Bear Bottom Clothing"},
    # footwear
    {"domain": "allbirds.com", "shop_name": "Allbirds"},
    {"domain": "toms.com", "shop_name": "TOMS"},
    {"domain": "rothys.com", "shop_name": "Rothy's"},
    # eyewear
    {"domain": "quayaustralia.com", "shop_name": "Quay Australia"},
    {"domain": "goodr.com", "shop_name": "Goodr"},
    {"domain": "pitviper.com", "shop_name": "Pit Viper"},
    # bags/accessories
    {"domain": "dagnedover.com", "shop_name": "Dagne Dover"},
    {"domain": "puravidabracelets.com", "shop_name": "Pura Vida Bracelets"},
    {"domain": "bando.com", "shop_name": "ban.do"},
    # outerwear
    {"domain": "taylorstitch.com", "shop_name": "Taylor Stitch"},
    {"domain": "rains.com", "shop_name": "Rains"},
    {"domain": "kavu.com", "shop_name": "KAVU"},
    # general apparel (hoodies/leggings/shorts depth)
    {"domain": "gymshark.com", "shop_name": "Gymshark"},
    {"domain": "chubbiesshorts.com", "shop_name": "Chubbies"},
]

PRODUCTS_PER_STORE = 250
MAX_PER_STORE_PER_TIER = 2
_WORD_RE = re.compile(r"[a-z0-9]+")

# Category names are free-form (Gemini writes whatever it thinks fits), so
# match against keyword groups rather than requiring an exact string equal
# to Shopify's own product_type/tag vocabulary.
CATEGORY_KEYWORDS = {
    # Deliberately no bare "top": marketing tags like "top-rated" or
    # "top-seller" tokenize down to "top" and would falsely match anything.
    "tops": {
        "tee", "tshirt", "shirt", "blouse", "sweater", "hoodie",
        "sweatshirt", "pullover", "tank", "crewneck", "polo", "henley",
    },
    "bottoms": {
        "pant", "pants", "jean", "jeans", "denim", "trouser", "trousers",
        "short", "shorts", "skirt", "legging", "leggings", "jogger", "joggers",
    },
    "outerwear": {
        "jacket", "coat", "outerwear", "parka", "blazer", "vest",
        "windbreaker", "raincoat", "puffer",
    },
    # No bare "flat": collides with tags like "flat-rate" once hyphens split.
    "footwear": {
        "shoe", "shoes", "sneaker", "sneakers", "boot", "boots", "sandal",
        "sandals", "footwear", "flats", "loafer", "loafers", "mule",
        "mules", "slipper",
    },
    "accessories": {
        "bag", "bags", "backpack", "wallet", "belt", "hat", "cap", "scarf",
        "jewelry", "bracelet", "necklace", "accessory", "accessories",
        "purse", "tote", "clutch",
    },
    "eyewear": {
        "sunglasses", "sunglass", "glasses", "eyewear", "shades", "goggle",
        "goggles",
    },
    "swimwear": {"swim", "swimsuit", "bikini", "trunk", "trunks", "swimwear"},
    "dresses": {"dress", "dresses", "gown"},
}

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


def _product_tokens(product: dict) -> set[str]:
    text = " ".join(
        [product.get("title", ""), product.get("product_type", ""), _tags_text(product.get("tags"))]
    )
    return _tokenize(text)


def _category_keywords(category: str) -> set[str]:
    cat = category.strip().lower()
    if not cat:
        return set()
    if cat in CATEGORY_KEYWORDS:
        return CATEGORY_KEYWORDS[cat]
    for key, words in CATEGORY_KEYWORDS.items():
        if key in cat or cat in key:
            return words
    return _tokenize(category)


# Color matches count several times more than a generic keyword hit, since a
# search for "black jacket" that returns the right jacket in the wrong color
# is a worse result than one that's a slightly looser style match.
COLOR_WEIGHT = 3.0
OTHER_WEIGHT = 1.0


def _relevance_score(search_tokens: set[str], color_tokens: set[str], product_tokens: set[str]) -> float:
    color_hits = len(color_tokens & product_tokens)
    other_hits = len(search_tokens & product_tokens)

    max_score = COLOR_WEIGHT * len(color_tokens) + OTHER_WEIGHT * len(search_tokens)
    if max_score == 0:
        return 0.0
    return (COLOR_WEIGHT * color_hits + OTHER_WEIGHT * other_hits) / max_score


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
    search_tokens = _tokenize(" ".join([search_query, material]))
    color_tokens = _tokenize(color)
    category_words = _category_keywords(category)

    scored = []
    for product in _get_all_products():
        product_tokens = _product_tokens(product)

        # Hard filter: a footwear query should never surface a dress just
        # because titles happen to share a color word. Products whose store
        # doesn't carry anything matching the category are excluded outright
        # rather than falling back to an unrelated "best available" match.
        if category_words and not (category_words & product_tokens):
            continue

        score = _relevance_score(search_tokens, color_tokens, product_tokens)
        if score <= 0:
            continue

        variant = _best_variant(product)
        if variant is not None:
            scored.append(_to_product(product, variant, score))

    return sorted(scored, key=lambda p: p.relevance_score, reverse=True)


def _pick_top(candidates: list[Product], n: int, cap_per_store: int = MAX_PER_STORE_PER_TIER) -> list[Product]:
    """Take the top n candidates (already ranked/filtered), capping how many
    can come from any single store so one deep catalog can't fill a whole
    tier by itself."""
    picked = []
    store_counts: dict[str, int] = {}
    for product in candidates:
        if store_counts.get(product.shop_name, 0) >= cap_per_store:
            continue
        picked.append(product)
        store_counts[product.shop_name] = store_counts.get(product.shop_name, 0) + 1
        if len(picked) == n:
            break
    return picked


def match_products(
    search_query: str, category: str, color: str, material: str
) -> tuple[list[Product], list[Product], list[Product]]:
    ranked = _rank(search_query, category, color, material)

    primary = _pick_top(ranked, 4)
    if not primary:
        return [], [], []

    used_upids = {p.upid for p in primary}
    remaining = [p for p in ranked if p.upid not in used_upids]
    median_price = statistics.median(p.price for p in primary)

    mid_candidates = [p for p in remaining if median_price * 0.5 <= p.price <= median_price]
    mid = _pick_top(mid_candidates, 4)
    used_upids |= {p.upid for p in mid}
    remaining = [p for p in remaining if p.upid not in used_upids]

    budget_candidates = [p for p in remaining if p.price < median_price * 0.5]
    budget = _pick_top(budget_candidates, 4)
    if not budget:
        budget = _pick_top(sorted(remaining, key=lambda p: p.price), 4)

    return primary, mid, budget
