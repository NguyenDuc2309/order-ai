from app.models.extraction import ExtractionResult
from app.services.ranker.scorer import StructuralScorer


def test_brand_match_adds_weight() -> None:
    extraction = ExtractionResult(product_name="coca", brand="coca cola")
    rows = [
        {"product": {"id": "1", "name": "Coca", "brand_norm": "coca cola"}, "score": 10.0},
    ]
    scored = StructuralScorer().score(rows, extraction)
    assert scored[0].structural_score >= 110.0


def test_brand_mismatch_penalty() -> None:
    extraction = ExtractionResult(product_name="coca", brand="coca cola")
    rows = [
        {"product": {"id": "1", "name": "Pepsi", "brand_norm": "pepsi"}, "score": 10.0},
    ]
    scored = StructuralScorer().score(rows, extraction)
    assert scored[0].structural_score == 0.01


def test_variant_penalty_applied() -> None:
    """Product with variant token gets penalised when user query is plain."""
    extraction = ExtractionResult(product_name="coca cola")
    rows = [
        {"product": {"id": "1", "name": "Coca Cola Zero 330ml"}, "score": 10.0},
        {"product": {"id": "2", "name": "Coca Cola 330ml"}, "score": 10.0},
    ]
    scored = StructuralScorer().score(rows, extraction)
    # Non-variant product must rank higher than variant product
    assert scored[0].product["id"] == "2"


def test_variant_penalty_not_applied_when_user_mentions_variant() -> None:
    """No penalty when user explicitly asks for a variant."""
    extraction = ExtractionResult(product_name="coca zero")
    rows = [
        {"product": {"id": "1", "name": "Coca Cola Zero 330ml"}, "score": 10.0},
        {"product": {"id": "2", "name": "Coca Cola 330ml"}, "score": 10.0},
    ]
    scored = StructuralScorer().score(rows, extraction)
    # Variant product should NOT be penalised — both have same score → ES order preserved
    assert scored[0].product["id"] == "1"
