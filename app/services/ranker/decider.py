import math
from dataclasses import dataclass
from typing import Literal

from app.core.config import config
from app.models.extraction import ExtractionResult
from app.services.ranker.scorer import ScoredRow
from app.utils.unit_converter import value_to_ml


@dataclass
class Decision:
    type: Literal["exact_match", "needs_clarification", "no_result"]
    confidence: float
    reason: str
    items: list[ScoredRow]


class Decider:
    """Quyết định type (exact_match / needs_clarification / no_result) và confidence.

    Logic: 3 gate theo thứ tự ưu tiên:
      1. no_result  — score thấp + không constraint nào khớp
      2. exact_match — AND gate: hard_pass + gap > threshold + audit_fraction >= 0.8
      3. needs_clarification — default (top_3_diverse)

    Confidence = 0.5 * sigmoid(gap/10) + 0.5 * audit_fraction.
    Không phải penalty-based, là composite của 2 independent signals.
    """

    def __init__(self) -> None:
        self.cfg = config.ranker

    def decide(self, scored_rows: list[ScoredRow], extraction: ExtractionResult) -> Decision:
        """Quyết định từ scored rows và extraction.

        Args:
            scored_rows: Output của StructuralScorer.score() — đã sorted desc
            extraction: ExtractionResult từ GeminiParser

        Returns:
            Decision với type, confidence, reason, items.
        """
        if not scored_rows:
            return Decision(type="no_result", confidence=1.0, reason="empty_catalog_result", items=[])

        top = scored_rows[0]
        top2 = scored_rows[1] if len(scored_rows) > 1 else None
        gap = top.structural_score - (top2.structural_score if top2 else 0.0)
        audit_fraction = self._audit_fraction(top)
        confidence = self._confidence(gap, audit_fraction)

        if (
            top.structural_score < self.cfg.min_relevance_score
            and top.audit.satisfied_count == 0
            and top.audit.specified_count >= 1
        ):
            no_result_conf = self._sigmoid((self.cfg.min_relevance_score - top.structural_score) / 5.0)
            return Decision(type="no_result", confidence=round(no_result_conf, 2), reason="low_relevance_no_match", items=[])

        gap_required = self.cfg.gap_exact_threshold if top.audit.soft_pass else self.cfg.gap_exact_threshold_strict
        if extraction.is_exact_request:
            gap_required = min(gap_required, self.cfg.gap_exact_threshold_explicit)

        is_exact = (
            top.audit.hard_pass
            and gap > gap_required
            and audit_fraction >= 0.8
        )
        if is_exact:
            return Decision(
                type="exact_match",
                confidence=round(confidence, 2),
                reason=f"hard_pass_gap_{gap:.2f}",
                items=[top],
            )

        return Decision(
            type="needs_clarification",
            confidence=round(confidence, 2),
            reason=f"clarify_gap_{gap:.2f}",
            items=self._top_3_diverse(scored_rows),
        )

    def _top_3_diverse(self, rows: list[ScoredRow]) -> list[ScoredRow]:
        if len(rows) <= 3:
            return rows
        best_seller = next((row for row in rows if row.product.get("is_best_seller")), rows[0])
        largest = max(rows, key=lambda row: value_to_ml(row.product.get("size_value"), row.product.get("size_unit")))
        smallest = min(rows, key=lambda row: value_to_ml(row.product.get("size_value"), row.product.get("size_unit")))
        picked: list[ScoredRow] = []
        seen: set[str] = set()
        for cand in (best_seller, largest, smallest):
            pid = str(cand.product.get("id"))
            if pid not in seen:
                picked.append(cand)
                seen.add(pid)
            if len(picked) == 3:
                return picked
        for row in rows:
            pid = str(row.product.get("id"))
            if pid in seen:
                continue
            picked.append(row)
            seen.add(pid)
            if len(picked) == 3:
                break
        return picked

    @staticmethod
    def _sigmoid(x: float) -> float:
        return 1.0 / (1.0 + math.exp(-x))

    def _confidence(self, gap: float, audit_fraction: float) -> float:
        base = self._sigmoid(gap / 10.0)
        return min(0.99, max(0.01, 0.5 * base + 0.5 * audit_fraction))

    @staticmethod
    def _audit_fraction(top: ScoredRow) -> float:
        return top.audit.satisfied_count / max(top.audit.specified_count, 1)
