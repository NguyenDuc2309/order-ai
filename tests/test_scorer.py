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


def test_best_seller_tie_break() -> None:
    extraction = ExtractionResult(product_name="water")
    rows = [
        {"product": {"id": "1", "name": "A", "is_best_seller": False}, "score": 10.0},
        {"product": {"id": "2", "name": "B", "is_best_seller": True}, "score": 10.0},
    ]
    scored = StructuralScorer().score(rows, extraction)
    assert scored[0].product["id"] == "2"
