from app.models.extraction import ExtractionResult
from app.services.ranker.constraint_audit import ConstraintAuditor, MatchState


def test_audit_hard_pass_for_coca_can() -> None:
    extraction = ExtractionResult(
        product_name="coca",
        brand="coca cola",
        category="Soft Drink",
        quantity=2,
        unit_raw="lon",
    )
    product = {
        "name": "Coca Cola lon 330ml",
        "brand_norm": "coca cola",
        "category_norm": "soft drink",
        "packaging": "lon",
    }
    result = ConstraintAuditor().audit(extraction, product)
    assert result.hard_pass is True
    assert result.must_not == MatchState.NOT_SPECIFIED


def test_audit_must_not_mismatch() -> None:
    extraction = ExtractionResult(
        product_name="coca",
        brand="coca cola",
        category="Soft Drink",
        quantity=2,
        unit_raw="lon",
        must_not=["light"],
    )
    product = {
        "name": "Coca Cola Light lon 330ml",
        "brand_norm": "coca cola",
        "category_norm": "soft drink",
        "packaging": "lon",
    }
    result = ConstraintAuditor().audit(extraction, product)
    assert result.must_not == MatchState.MISMATCH


def test_audit_out_of_catalog_like_query() -> None:
    extraction = ExtractionResult(product_name="iphone", brand="iphone", category="Phone")
    product = {
        "name": "Sữa tắm Lux",
        "brand_norm": "lux",
        "category_norm": "personal care",
        "packaging": "chai",
    }
    result = ConstraintAuditor().audit(extraction, product)
    assert result.satisfied_count == 0
    assert result.specified_count >= 1


def test_attributes_partial_ratio() -> None:
    extraction = ExtractionResult(
        product_name="coca",
        attributes=["zero", "vanilla"],
    )
    product = {
        "name": "Coca Cola Zero lon 330ml",
        "brand_norm": "coca cola",
        "category_norm": "soft drink",
        "packaging": "lon",
        "tags": ["zero"],
    }
    result = ConstraintAuditor().audit(extraction, product)
    assert result.attributes == MatchState.PARTIAL
    assert result.attributes_ratio == 0.5
