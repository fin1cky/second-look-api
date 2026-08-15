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
curated list of 17 real Shopify storefronts — a public, unauthenticated
endpoint every Shopify store exposes, and one that Modal *can* reach. Each
store's catalog is fetched once and cached in memory (never re-fetched per
request). Note that some familiar mainstream retailers (Nike, Adidas, Uniqlo,
H&M, Gap, Abercrombie, Hollister, Tommy Hilfiger) simply aren't Shopify-hosted
and can never appear here regardless of curation.

A search ranks cached products in three steps:
1. **Category filter** — hard-excludes products whose `product_type`/`tags`
   share no keyword with the requested `category` (matched via a synonym
   map, since categories are free-form text from Gemini, not a fixed enum).
   This is what stops a sunglasses query from ever returning shoes.
2. **Weighted relevance score** — token overlap between the query
   (`search_query` + `material`) and each product's title/type/tags, with
   `color` weighted 3x a generic keyword hit so a color-correct result
   outranks a looser style match in the wrong color.
3. **Per-store cap** — each tier (`primary`/`mid`/`budget`) allows at most 2
   items from any single store, so one deep catalog can't fill an entire
   tier by itself.

Trade-offs worth knowing:
- Relevance comes from token overlap against 17 stores, not Shopify's own
  cross-merchant search ranking — a stand-in, not equivalent coverage. A
  query for something none of the 17 stores carry will still return its
  nearest keyword matches rather than nothing.
- Every result is new: single-brand storefronts don't carry secondhand
  inventory, so `is_secondhand` is always `false` today (the Catalog API path
  in `app/catalog.py` does support a real secondhand signal).
- Keyword matching has occasional false positives from ambiguous retail
  vocabulary (e.g. jewelry "ear jackets" surfacing on an outerwear-adjacent
  "jacket" search) — an inherent limit of this approach, not a bug to chase
  to zero.

The 17 stores (`app/storefronts.py: STORES`), verified reachable and with
real catalog depth (20-50+ SKUs sampled per store):

| Store | Category | Rough price range |
|---|---|---|
| True Classic | basics/staples (tees) | $63–$150 |
| Fresh Clean Tees | basics/staples (tees) | $16–$136 |
| Bear Bottom Clothing | basics/staples | $15–$288 |
| Allbirds | footwear (sneakers) | $3–$160 |
| TOMS | footwear (casual shoes) | $50–$110 |
| Rothy's | footwear (flats) | $55–$225 |
| Quay Australia | eyewear | $29–$370 |
| Goodr | eyewear | $30–$50 |
| Pit Viper | eyewear | $14–$120 |
| Dagne Dover | bags/accessories | $7–$675 |
| Pura Vida Bracelets | bags/accessories | $3–$90 |
| ban.do | bags/accessories | $12–$248 |
| Taylor Stitch | outerwear | $55–$278 |
| Rains | outerwear | $15–$529 |
| KAVU | outerwear | $18–$135 |
| Gymshark | apparel (athleisure) | $25–$64 |
| Chubbies | apparel (bottoms) | $40–$90 |

Premium anchors: Rothy's, Dagne Dover, Taylor Stitch, Rains. Budget anchors:
Fresh Clean Tees, Bear Bottom Clothing, Goodr, Pura Vida Bracelets.

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
