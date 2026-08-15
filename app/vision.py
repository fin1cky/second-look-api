"""Gemini-powered garment detection for /analyze."""

import base64
import json
import os
import time

import httpx
from fastapi import HTTPException
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.schemas import AnalyzeItem, AnalyzeResponse

MODEL = "gemini-flash-latest"
MAX_ITEMS = 5
MAX_RETRIES = 2

PROMPT = (
    "Identify every distinct garment or accessory worn or shown in this image, "
    "most prominent first, up to 5 items. For each item, determine: label (short "
    "human-readable name), category (e.g. outerwear, tops, bottoms, footwear, "
    "accessories), color, material, style_descriptors (2-4 short style keywords), "
    "a search_query string phrased the way a shopper would search a product "
    "catalog for this exact item, and a confidence score from 0 to 1. "
    "Respond with JSON only, matching the response schema exactly — no prose, "
    "no markdown fencing, no explanation."
)

_ITEM_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "label": types.Schema(type=types.Type.STRING),
        "category": types.Schema(type=types.Type.STRING),
        "color": types.Schema(type=types.Type.STRING),
        "material": types.Schema(type=types.Type.STRING),
        "style_descriptors": types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING)),
        "search_query": types.Schema(type=types.Type.STRING),
        "confidence": types.Schema(type=types.Type.NUMBER),
    },
    required=["label", "category", "color", "material", "style_descriptors", "search_query", "confidence"],
)

RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "items": types.Schema(type=types.Type.ARRAY, items=_ITEM_SCHEMA, max_items=MAX_ITEMS),
    },
    required=["items"],
)

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


def _load_image(image_url: str | None, image_base64: str | None) -> tuple[bytes, str]:
    if image_base64:
        return base64.b64decode(image_base64), "image/jpeg"

    if image_url:
        try:
            response = httpx.get(image_url, timeout=15.0, follow_redirects=True)
            response.raise_for_status()
        except httpx.HTTPError as e:
            raise HTTPException(status_code=400, detail=f"Could not fetch image_url: {e}")
        mime_type = response.headers.get("content-type", "image/jpeg").split(";")[0]
        return response.content, mime_type

    raise HTTPException(status_code=400, detail="Provide either image_url or image_base64.")


def _generate(image_bytes: bytes, mime_type: str):
    for attempt in range(MAX_RETRIES + 1):
        try:
            return _get_client().models.generate_content(
                model=MODEL,
                contents=[types.Part.from_bytes(data=image_bytes, mime_type=mime_type), PROMPT],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=RESPONSE_SCHEMA,
                ),
            )
        except genai_errors.ServerError:
            if attempt == MAX_RETRIES:
                raise
            time.sleep(2**attempt)


def analyze_image(image_url: str | None, image_base64: str | None) -> AnalyzeResponse:
    image_bytes, mime_type = _load_image(image_url, image_base64)

    try:
        response = _generate(image_bytes, mime_type)
    except genai_errors.APIError as e:
        raise HTTPException(status_code=502, detail=f"Gemini API error: {e}")

    data = json.loads(response.text)
    items = [AnalyzeItem(**item) for item in data.get("items", [])][:MAX_ITEMS]
    return AnalyzeResponse(items=items)
