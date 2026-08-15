"""Hardcoded sample payload used until the real vision model call lands."""

from app.schemas import AnalyzeItem, AnalyzeResponse

SAMPLE_ANALYZE_RESPONSE = AnalyzeResponse(
    items=[
        AnalyzeItem(
            label="Oversized denim jacket",
            category="outerwear",
            color="light blue",
            material="denim",
            style_descriptors=["oversized", "distressed", "vintage"],
            search_query="oversized light blue distressed denim jacket",
            confidence=0.94,
        ),
        AnalyzeItem(
            label="White ribbed tank top",
            category="tops",
            color="white",
            material="cotton",
            style_descriptors=["ribbed", "fitted", "casual"],
            search_query="white ribbed fitted tank top",
            confidence=0.89,
        ),
        AnalyzeItem(
            label="Black leather chelsea boots",
            category="footwear",
            color="black",
            material="leather",
            style_descriptors=["chelsea", "chunky sole", "minimalist"],
            search_query="black leather chelsea boots chunky sole",
            confidence=0.91,
        ),
    ]
)
