from app.models.extraction import ExtractionResult
from app.services.ranker.constraint_audit import AuditResult, MatchState
from app.services.ranker.decider import Decider
from app.services.ranker.scorer import ScoredRow


def make_row(pid: str, score: float, satisfied: int, specified: int, hard: bool, soft: bool):
    return ScoredRow(
        product={"id": pid, "name": pid, "size_value": 330, "size_unit": "ml"},
        raw_es_score=1.0,
        structural_score=score,
        audit=AuditResult(
            brand=MatchState.MATCH,
            category=MatchState.MATCH,
            size=MatchState.MATCH,
            packaging=MatchState.MATCH,
            attributes=MatchState.NOT_SPECIFIED,
            attributes_ratio=0.0,
            must_not=MatchState.NOT_SPECIFIED,
            hard_pass=hard,
            soft_pass=soft,
            satisfied_count=satisfied,
            specified_count=specified,
        ),
    )


def test_exact_match_case() -> None:
    # is_specific dựa vào brand/unit_raw/size_value (P1 — FACT, không phán đoán)
    extracted = ExtractionResult(product_name="coca", brand="coca cola", unit_raw="lon")
    rows = [make_row("a", 100.0, 4, 4, True, True), make_row("b", 60.0, 1, 4, False, False)]
    decision = Decider().decide(rows, extracted)
    assert decision.type == "exact_match"
    assert decision.confidence >= 0.85


def test_no_result_case() -> None:
    extracted = ExtractionResult(product_name="iphone", brand="iphone", category="phone")
    rows = [make_row("x", 5.0, 0, 2, False, False)]
    decision = Decider().decide(rows, extracted)
    assert decision.type == "no_result"
    assert decision.confidence < 1.0


def test_needs_clarification_case() -> None:
    extracted = ExtractionResult(product_name="coca", brand="coca cola")
    rows = [make_row("a", 80.0, 1, 1, True, True), make_row("b", 78.0, 1, 1, True, True), make_row("c", 77.0, 1, 1, True, True)]
    decision = Decider().decide(rows, extracted)
    assert decision.type == "needs_clarification"
    assert len(decision.items) == 3
