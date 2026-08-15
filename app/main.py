"""Second Look API: vision-based garment analysis + Shopify catalog matching."""

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.catalog import AGENT_PROFILE
from app.schemas import AnalyzeRequest, AnalyzeResponse, MatchRequest, MatchResponse
from app.storefronts import match_products
from app.vision import analyze_image

app = FastAPI(title="Second Look API", version="0.1.0")


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ucp-agent-profile.json")
def ucp_agent_profile() -> JSONResponse:
    return JSONResponse(AGENT_PROFILE)


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    return analyze_image(request.image_url, request.image_base64)


@app.post("/match", response_model=MatchResponse)
def match(request: MatchRequest) -> MatchResponse:
    primary, mid, budget = match_products(
        request.search_query, request.category, request.color, request.material
    )
    return MatchResponse(primary=primary, mid=mid, budget=budget)
