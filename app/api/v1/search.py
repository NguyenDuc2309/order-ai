from fastapi import APIRouter

from app.graph.pipeline import pipeline
from app.models.request import SearchRequest
from app.models.response import SearchResponse

router = APIRouter()


@router.post("/search/product", response_model=SearchResponse)
def search_product(payload: SearchRequest) -> SearchResponse:
    result = pipeline.invoke(
        {
            "query": payload.query,
            "user_id": payload.user_id,
        }
    )
    return result["response"]
