from typing import TypedDict

from app.models.extraction import ExtractionResult
from app.models.response import SearchResponse


class SearchState(TypedDict, total=False):
    query: str
    user_id: str
    extraction: ExtractionResult
    query_vector: list[float]
    es_query: dict
    hits: list[dict]
    response: SearchResponse
