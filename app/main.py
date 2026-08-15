"""Second Look API: vision-based garment analysis + Shopify catalog matching."""

from fastapi import FastAPI

from app.fixtures import SAMPLE_ANALYZE_RESPONSE, SAMPLE_MATCH_RESPONSE
from app.schemas import AnalyzeRequest, AnalyzeResponse, MatchRequest, MatchResponse

app = FastAPI(title="Second Look API", version="0.1.0")


@app.get("/")
def health() -> dict:
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(request: AnalyzeRequest) -> AnalyzeResponse:
    return SAMPLE_ANALYZE_RESPONSE


@app.post("/match", response_model=MatchResponse)
def match(request: MatchRequest) -> MatchResponse:
    return SAMPLE_MATCH_RESPONSE
