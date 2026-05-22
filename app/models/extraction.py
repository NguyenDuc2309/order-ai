from typing import Literal

from pydantic import BaseModel, Field


class ExtractionResult(BaseModel):
    product_name: str
    brand: str | None = None
    category: str | None = None
    unit_raw: str | None = None
    size_value: float | None = None
    size_unit: str | None = None
    size_hint: Literal["large", "small", "medium"] | None = None
    attributes: list[str] = Field(default_factory=list)
    must_not: list[str] = Field(default_factory=list)
