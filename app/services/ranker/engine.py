from app.core.logging_config import setup_audit_logger
from app.models.extraction import ExtractionResult
from app.models.response import SearchItem, SearchResponse
from app.services.ranker.constraint_audit import ConstraintAuditor
from app.services.ranker.decider import Decider, Decision
from app.services.ranker.scorer import StructuralScorer


class RankingEngine:
    """Orchestrator cho toàn bộ ranking pipeline.

    Flow: rows → StructuralScorer → Decider → SearchResponse
    Ghi structured audit log (query, extraction, top_product, audit, decision) sau mỗi call.

    Usage:
        engine = RankingEngine()
        response = engine.decide(extracted, rows, original_query)
    """

    def __init__(self) -> None:
        self.auditor = ConstraintAuditor()
        self.scorer = StructuralScorer()
        self.decider = Decider()
        self.audit_logger = setup_audit_logger()

    def decide(
        self,
        extracted: ExtractionResult,
        rows: list[dict],
        original_query: str = "",
    ) -> SearchResponse:
        if not rows:
            decision = self.decider.decide([], extracted)
            self._log_audit(extracted, None, decision, original_query)
            return self._to_response(decision, extracted)

        scored_rows = self.scorer.score(rows, extracted)
        decision = self.decider.decide(scored_rows, extracted)
        self._log_audit(extracted, scored_rows[0], decision, original_query)
        return self._to_response(decision, extracted)

    def _to_response(self, decision: Decision, extracted: ExtractionResult) -> SearchResponse:
        if decision.type == "exact_match":
            top = decision.items[0]
            return SearchResponse(
                status="success",
                type="exact_match",
                confidence=decision.confidence,
                items=[
                    SearchItem(
                        id=top.product["id"],
                        name=top.product["name"],
                        quantity=extracted.quantity,
                        score=top.structural_score,
                    )
                ],
                message=f"Đã chọn {top.product['name']} và thêm {extracted.quantity} sản phẩm vào giỏ.",
            )
        if decision.type == "no_result":
            return SearchResponse(
                status="success",
                type="no_result",
                confidence=decision.confidence,
                items=[],
                message="Không tìm thấy sản phẩm phù hợp, bạn thử mô tả chi tiết hơn nhé.",
            )
        return SearchResponse(
            status="success",
            type="needs_clarification",
            confidence=decision.confidence,
            items=[
                SearchItem(
                    id=row.product["id"],
                    name=row.product["name"],
                    quantity=extracted.quantity,
                    score=row.structural_score,
                )
                for row in decision.items
            ],
            message="Mình tìm thấy vài lựa chọn gần nhất, bạn chọn giúp mình sản phẩm phù hợp nhé.",
        )

    def _log_audit(self, extracted: ExtractionResult, top, decision: Decision, query: str) -> None:
        top_product = top.product["name"] if top else ""
        audit_payload = {}
        if top:
            audit_payload = self.auditor.to_dict(top.audit)
        self.audit_logger.info(
            "ranking_engine_decision",
            extra={
                "event": {
                    "query": query,
                    "extraction": extracted.model_dump(),
                    "top_product": top_product,
                    "audit": audit_payload,
                    "decision": {
                        "type": decision.type,
                        "confidence": decision.confidence,
                        "reason": decision.reason,
                        "item_ids": [str(item.product.get("id")) for item in decision.items],
                    },
                }
            },
        )
