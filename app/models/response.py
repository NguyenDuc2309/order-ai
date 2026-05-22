from typing import Literal

from pydantic import BaseModel


class SearchItem(BaseModel):
    id: str
    name: str
    score: float | None = None


class SearchResponse(BaseModel):
    status: Literal["success", "error"]
    type: Literal["exact_match", "needs_clarification", "no_result"]
    confidence: float
    items: list[SearchItem]
    message: str
