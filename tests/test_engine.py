from app.models.extraction import ExtractionResult
from app.services.ranker.engine import RankingEngine


def test_engine_exact_match() -> None:
    engine = RankingEngine()
    extraction = ExtractionResult(product_name="coca", brand="coca cola", category="soft drink")
    rows = [
        {"product": {"id": "1", "name": "Coca Cola lon 330ml", "brand_norm": "coca cola", "category_norm": "soft drink", "packaging": "lon", "size_value": 330, "size_unit": "ml"}, "score": 20.0},
        {"product": {"id": "2", "name": "Pepsi lon 330ml", "brand_norm": "pepsi", "category_norm": "soft drink", "packaging": "lon", "size_value": 330, "size_unit": "ml"}, "score": 1.0},
    ]
    res = engine.decide(extraction, rows, "coca lon")
    assert res.type == "exact_match"
    assert res.items[0].id == "1"
    assert res.items[0].name == "Coca Cola lon 330ml"


def test_engine_no_result_for_empty_rows() -> None:
    engine = RankingEngine()
    extraction = ExtractionResult(product_name="iphone")
    res = engine.decide(extraction, [], "iphone")
    assert res.type == "no_result"
