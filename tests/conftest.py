import pytest

from app.models.extraction import ExtractionResult


@pytest.fixture
def sample_extraction() -> ExtractionResult:
    return ExtractionResult(
        product_name="coca",
        brand="coca cola",
        category="soft drink",
        unit_raw="lon",
    )


@pytest.fixture
def sample_product() -> dict:
    return {
        "id": "sku-1",
        "name": "Coca Cola lon 330ml",
        "brand_norm": "coca cola",
        "category": "soft drink",
        "category_norm": "soft drink",
        "packaging": "lon",
        "tags": ["zero", "diet"],
    }
