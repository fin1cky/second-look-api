# Second Look API

Turn a photo of an outfit into shoppable Shopify product matches. Point it at
an image, get back the individual garments detected in it; feed one of those
garments back in and get real product listings at both a primary price point
and a budget-friendly one.

Built for a Shopify hackathon. Deployed on [Modal](https://modal.com).

**Live URL:** https://fin1cky--second-look-api-fastapi-app.modal.run

## Status

Endpoints are live with hardcoded sample responses so the shape of the API is
locked in and the frontend can integrate against it immediately. The vision
model call and the Shopify Catalog API integration land next — see
[Roadmap](#roadmap).

## Endpoints

### `POST /analyze`

Detects garments in a photo.

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

Capped at 5 items per image.

### `POST /match`

Finds shoppable products for a single garment.

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
      "title": "Oversized Distressed Denim Jacket",
      "brand": "Levi's",
      "price": 128.0,
      "currency": "USD",
      "image_url": "https://...",
      "product_url": "https://...",
      "shop_name": "Levi's",
      "is_secondhand": false,
      "upid": "upid_primary_001"
    }
  ],
  "budget": [ "...same shape, cheaper..." ]
}
```

`primary` is the top 4 results for the query as-is. `budget` re-runs the same
query with `max_price` capped at 50% of `primary`'s median price, top 4.

## Architecture

```
app/
  main.py       FastAPI app, route definitions
  schemas.py    Pydantic request/response models
  fixtures.py   Hardcoded sample payloads (current stand-in for real calls)
modal_app.py    Modal deployment entrypoint (modal deploy modal_app.py)
```

Once real integrations are in:
- `/analyze` calls a vision model with a structured-output-only prompt (no
  prose), parses the JSON, caps results at 5 items.
- `/match` hits the Shopify Catalog API
  (`https://discover.shopifyapps.com/global/v2/search`). The catalog JWT is
  cached in memory and refreshed on expiry (~60 min) rather than fetched per
  request.

## Local development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Deploying

```bash
modal deploy modal_app.py
```

Prints the live URL on success.

## Roadmap

- [ ] `/analyze`: real vision model call, structured JSON output, 5-item cap
- [ ] `/match`: real Shopify Catalog API integration with cached/refreshed JWT
- [ ] `/match`: budget tier priced off primary's median
