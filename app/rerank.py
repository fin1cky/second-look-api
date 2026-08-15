"""LLM rerank pass for /match: strict same-category filter over-fetched keyword results.

Keyword ranking (category filter + color-weighted token overlap in
app/storefronts.py) casts a wide net but still lets through same-tag noise —
e.g. a boxer brief showing up for "black round sunglasses" because both got
cross-tagged under a store's "Accessories" taxonomy. This sends the
over-fetched candidate pool to Gemini once per /match request and asks it to
keep only genuinely same-category items, ranked best first.

This is a quality pass, not a dependency: any failure (timeout, bad
response, quota, network error) returns None, and the caller falls back to
the plain keyword ranking. /match must never break because Gemini is slow,
rate-limited, or down.
"""

import json
import os

from google import genai
from google.genai import types

from app.schemas import Product

MODEL = "gemini-flash-latest"
TIMEOUT_MS = 8_000

PROMPT_TEMPLATE = """A shopper is looking for a specific item with these attributes:
- label: {label}
- category: {category}
- color: {color}
- material: {material}
- style: {style_descriptors}

Below is a list of candidate products (id, title, brand, price) pulled by a keyword search.
Some of these are NOT actually the same kind of item as the target — they only surfaced
because of loose keyword or tag overlap (for example, a boxer brief showing up for a
"black round sunglasses" search). Be strict: exclude anything that is not genuinely the
same product category as the target, even if it shares color, material, or brand.

Return the ids of only the genuine matches, ordered best match first. It is better to
return fewer results than to include a bad one. If none of the candidates are good
matches, return an empty list.

Candidates:
{candidates}
"""

RESULT_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "ranked_ids": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
    },
    required=["ranked_ids"],
)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _build_prompt(by_id: dict[str, Product], label: str, category: str, color: str, material: str, style_descriptors: list[str]) -> str:
    candidate_lines = "\n".join(
        f'- id={cid}, title="{p.title}", brand="{p.brand}", price={p.price}' for cid, p in by_id.items()
    )
    return PROMPT_TEMPLATE.format(
        label=label,
        category=category,
        color=color,
        material=material,
        style_descriptors=", ".join(style_descriptors) if style_descriptors else "none",
        candidates=candidate_lines,
    )


def rerank(
    candidates: list[Product],
    label: str,
    category: str,
    color: str,
    material: str,
    style_descriptors: list[str],
) -> list[Product] | None:
    """Filter + reorder candidates by genuine category match. None on any failure."""
    if not candidates:
        return []

    by_id = {str(i): p for i, p in enumerate(candidates)}
    prompt = _build_prompt(by_id, label, category, color, material, style_descriptors)

    try:
        response = _get_client().models.generate_content(
            model=MODEL,
            contents=[prompt],
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=RESULT_SCHEMA,
                http_options=types.HttpOptions(timeout=TIMEOUT_MS),
            ),
        )
        data = json.loads(response.text)
        seen = set()
        result = []
        for cid in data.get("ranked_ids", []):
            if cid in by_id and cid not in seen:
                seen.add(cid)
                result.append(by_id[cid])
        return result
    except Exception:
        return None
