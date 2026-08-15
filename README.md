# Second Look API

Turn a photo of an outfit into shoppable product matches. Point it at an
image, get back the individual garments detected in it; feed one of those
garments back in and get real product listings spanning a splurge-to-budget
price spread.

Built for a Shopify hackathon. Deployed on [Modal](https://modal.com).

**Live URL:** https://fin1cky--second-look-api-fastapi-app.modal.run

## Status

Both endpoints are live against real data: `/analyze` calls Gemini for
structured garment detection, `/match` hits real, live product data (see
[How /match sources products](#how-match-sources-products) below for why
it's not Shopify's centralized Catalog API).

## Endpoints

### `POST /analyze`

Detects garments in a photo using Gemini (`gemini-flash-latest`), forced to
structured JSON output via a response schema — no prose, no markdown
fencing.

**Request**
```json
{ "image_url": "https://example.com/outfit.jpg" }
```
or
```json
{ "image_base64": "..." }
```

**Response**
```json
{
  "items": [
    {
      "label": "Oversized denim jacket",
      "category": "outerwear",
      "color": "light blue",
      "material": "denim",
      "style_descriptors": ["oversized", "distressed", "vintage"],
      "search_query": "oversized light blue distressed denim jacket",
      "confidence": 0.94
    }
  ]
}
```

Capped at 5 items per image (enforced both in the response schema and again
in code).

### `POST /match`

Finds shoppable products for a single garment, ranked into three price tiers.

**Request**
```json
{
  "search_query": "oversized light blue distressed denim jacket",
  "category": "outerwear",
  "color": "light blue",
  "material": "denim",
  "style_descriptors": ["oversized", "distressed", "vintage"]
}
```

**Response**
```json
{
  "primary": [
    {
      "title": "The Long Haul Jacket in Mid Wash Organic Selvedge",
      "brand": "Taylor Stitch",
      "price": 228.0,
      "currency": "USD",
      "image_url": "https://...",
      "product_url": "https://...",
      "shop_name": "Taylor Stitch",
      "is_secondhand": false,
      "upid": "taylorstitch.com:7645557194829",
      "relevance_score": 0.8
    }
  ],
  "mid": [ "...same shape, mid-priced..." ],
  "budget": [ "...same shape, cheapest..." ]
}
```

All three tiers are price slices of one ranked-by-relevance pool, not
separate searches:

- **`primary`** — top 4 matches by relevance, any price. The "exact thing"
  tier; a great match isn't excluded for being expensive.
- **`mid`** — next-best matches (continuing down the ranked list) priced
  between 50% and 100% of `primary`'s median price, up to 4.
- **`budget`** — next-best matches priced under 50% of `primary`'s median, up
  to 4. If nothing qualifies at that price, falls back to the cheapest
  remaining matches rather than returning empty.

## How `/analyze` uses Gemini

`app/vision.py` sends the image (fetched and base64'd if given as a URL) plus
a prompt to `gemini-flash-latest` with `response_mime_type=application/json`
and an explicit `response_schema`, so Gemini can't return prose — only JSON
matching the item shape above. The Gemini API key is read from the
`gemini-api-key` Modal secret (`GEMINI_API_KEY`), never hardcoded. Transient
`503`s from Gemini (demand spikes are common) get retried twice with backoff
before surfacing as a `502` to the caller.

## How `/match` sources products

The original design called for Shopify's centralized Catalog API
(`discover.shopifyapps.com` / `catalog.shopify.com`). Both are unreachable
from Modal: Cloudflare bot-protection hard-blocks Modal's egress IP on every
retry, on both the REST search endpoint and its newer MCP-based replacement.
Confirmed by testing the identical request from a residential network
(succeeds) versus from Modal (blocked every time) — this isn't a code, auth,
or scope bug. `app/catalog.py` keeps both working client implementations
(REST + MCP) for whenever that egress path is unblocked (see the module
docstring for the full diagnosis).

Instead, `app/storefronts.py` fetches `/products.json` directly from a
curated list of ten real Shopify storefronts — a public, unauthenticated
endpoint every Shopify store exposes, and one that Modal *can* reach. Each
store's catalog is fetched once and cached in memory (never re-fetched per
request). A search ranks all cached products by keyword overlap between the
query (`search_query` + `category` + `color` + `material`) and each
product's title/type/tags, then slices the ranked list into the three price
tiers above.

Trade-offs worth knowing:
- Relevance comes from token overlap against ten stores, not Shopify's own
  cross-merchant search ranking — a stand-in, not equivalent coverage. A
  query for something none of the ten stores carry (e.g. dress shoes) will
  still return its nearest keyword matches rather than nothing.
- Every result is new: single-brand storefronts don't carry secondhand
  inventory, so `is_secondhand` is always `false` today (the Catalog API path
  in `app/catalog.py` does support a real secondhand signal).
- The ten stores (`app/storefronts.py: STORES`) span footwear, apparel,
  homeware, and accessories across premium, mid, and budget price points —
  chosen and verified reachable specifically to make all three tiers show a
  real spread.

## Architecture

```
app/
  main.py         FastAPI app, route definitions
  schemas.py      Pydantic request/response models
  vision.py       Real /analyze implementation: Gemini structured-output call
  storefronts.py  Real /match implementation: per-store product cache + ranking
  catalog.py      Shopify Catalog API clients (REST + MCP) — unused today,
                  blocked by Cloudflare from Modal's egress; kept for when
                  that's resolved
modal_app.py      Modal deployment entrypoint (modal deploy modal_app.py)
```

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export GEMINI_API_KEY=...  # only needed to exercise /analyze locally
uvicorn app.main:app --reload
```

## Deploying

```bash
modal deploy modal_app.py
```

Prints the live URL on success. Requires the `gemini-api-key` Modal secret
(`GEMINI_API_KEY`) to be set up beforehand.

## Roadmap

- [ ] `/match`: unblock Shopify Catalog API egress from Modal (static IP +
      allowlist, or another path) and switch back to `app/catalog.py` for
      real cross-merchant search + secondhand data
