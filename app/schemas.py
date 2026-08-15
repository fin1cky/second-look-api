"""Pydantic models shared by the /analyze and /match endpoints."""

from pydantic import BaseModel, Field


class AnalyzeRequest(BaseModel):
    image_url: str | None = None
    image_base64: str | None = None


class AnalyzeItem(BaseModel):
    label: str
    category: str
    color: str
    material: str
    style_descriptors: list[str]
    search_query: str
    confidence: float


class AnalyzeResponse(BaseModel):
    items: list[AnalyzeItem] = Field(..., max_length=5)


class MatchRequest(BaseModel):
    search_query: str
    category: str
    color: str
    material: str
    style_descriptors: list[str]


class Product(BaseModel):
    title: str
    brand: str
    price: float
    currency: str
    image_url: str
    product_url: str
    shop_name: str
    is_secondhand: bool
    upid: str
    relevance_score: float


class MatchResponse(BaseModel):
    primary: list[Product]
    mid: list[Product]
    budget: list[Product]
