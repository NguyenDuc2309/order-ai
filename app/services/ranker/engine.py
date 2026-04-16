import math
from app.core.clients.gemini import GeminiClient
from app.models.extraction import ExtractionResult
from app.models.response import SearchItem, SearchResponse
from app.services.ranker.reranker import GeminiReranker
from app.services.ranker.scoring import ScoringRanker
from app.utils.unit_converter import value_to_ml


class RankingEngine:
    def __init__(self) -> None:
        self.scorer = ScoringRanker()
        self.reranker = GeminiReranker(gemini_client=GeminiClient())

    def decide(
        self,
        extracted: ExtractionResult,
        rows: list[dict],
        original_query: str = "",
    ) -> SearchResponse:
        if not rows:
            return SearchResponse(
                status="success",
                type="no_result",
                confidence=0.0,
                items=[],
                message="Không tìm thấy sản phẩm phù hợp, bạn thử mô tả chi tiết hơn nhé.",
            )

        # 1. Scoring (Deterministic Backend Rules)
        scored_rows = self.scorer.score(rows, extracted)
        top_1 = scored_rows[0]
        top_2 = scored_rows[1] if len(scored_rows) > 1 else None
        
        # 2. Advanced Confidence Formula
        # Based on sigmoid of score gap and absolute match quality
        top_score = top_1["score"]
        gap = (top_score - top_2["score"]) if top_2 else top_score
        
        # Determine confidence based on "Score Bands"
        # If score > 100 -> likely Brand match. If gap > 20 -> very likely correct.
        base_conf = 1 / (1 + math.exp(-gap / 10.0)) # Sigmoid of gap
        
        # Adjust confidence by matches
        matches_all_constraints = (
            self.scorer.size_match(top_1["product"], extracted)
            and (not extracted.brand or str(top_1["product"].get("brand", "")).lower() == extracted.brand.lower())
        )
        
        if matches_all_constraints and top_score > 100:
            confidence = 0.95 + (0.04 * base_conf)
        elif matches_all_constraints:
            confidence = 0.85 + (0.1 * base_conf)
        else:
            confidence = base_conf * 0.7 # Penalize for mismatch
            
        confidence = round(min(0.99, max(0.01, confidence)), 2)
        
        # 3. Decision Logic - BACKEND CONFIDENCE DRIVEN
        # Backend score/gap overrides LLM extraction flags
        # Exact match criteria:
        # - High confidence (>= 0.85) 
        # - Clear winner (gap > 20 for matched constraints, or gap > 40 otherwise)
        # - All constraints matched
        
        gap_threshold = 20 if matches_all_constraints else 40
        
        is_exact = (
            confidence >= 0.85 and 
            gap > gap_threshold and
            matches_all_constraints
        )

        if is_exact:
            return SearchResponse(
                status="success",
                type="exact_match",
                confidence=confidence,
                items=[
                    SearchItem(
                        id=top_1["product"]["id"],
                        name=top_1["product"]["name"],
                        quantity=extracted.quantity,
                        score=top_score,
                    )
                ],
                message=f"Đã chọn {top_1['product']['name']} và thêm {extracted.quantity} sản phẩm vào giỏ.",
            )

        # Scenario B: Needs Clarification (3 items)
        choices = self._top_three_diverse(scored_rows)
        return SearchResponse(
            status="success",
            type="needs_clarification",
            confidence=confidence,
            items=[
                SearchItem(
                    id=r["product"]["id"], 
                    name=r["product"]["name"], 
                    score=r["score"],
                    quantity=extracted.quantity # Support quantity here too
                ) for r in choices
            ],
            message="Mình tìm thấy vài lựa chọn gần nhất, bạn chọn giúp mình sản phẩm phù hợp nhé.",
        )

    def _top_three_diverse(self, rows: list[dict]) -> list[dict]:
        best_seller = next((r for r in rows if r["product"]["is_best_seller"]), rows[0])
        
        def get_ml(r):
            return value_to_ml(r["product"].get("size_value"), r["product"].get("size_unit"))

        largest = max(rows, key=get_ml)
        smallest = min(rows, key=get_ml)
        
        picked = []
        for row in [best_seller, largest, smallest]:
            if row["product"]["id"] not in {p["product"]["id"] for p in picked}:
                picked.append(row)
            if len(picked) == 3:
                break
        return picked