import math
import re
from dataclasses import dataclass
from typing import Literal

from app.core.config import config
from app.models.extraction import ExtractionResult
from app.services.ranker.constraint_audit import MatchState
from app.services.ranker.scorer import ScoredRow, VARIANT_TOKENS
from app.utils.unit_converter import value_to_ml

_NEGATIVE_ATTR_RE = re.compile(r"^(không|ít|tách|no|low)\s+", re.IGNORECASE)


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

        # no_result gate: user đã specify ít nhất 1 constraint nhưng không constraint nào
        # được thỏa bởi top-1. Đây là tín hiệu rõ ràng catalog không có sản phẩm phù hợp.
        # Không cần điều kiện score vì brand/category MISMATCH đã trừ điểm nặng (-50/-20);
        # giữ điều kiện score như backup cho trường hợp specified_count=0 (query không có constraint).
        if top.audit.satisfied_count == 0 and top.audit.specified_count >= 1:
            return Decision(type="no_result", confidence=0.95, reason="no_constraint_satisfied", items=[])

        # Brand MISMATCH + weak match + low score → likely OOC even if 1 weak constraint matched
        if (
            top.audit.brand == MatchState.MISMATCH
            and top.audit.satisfied_count <= 1
            and top.structural_score < self.cfg.min_relevance_score * 1.5  # 45
        ):
            return Decision(type="no_result", confidence=0.85, reason="brand_missed_low_score", items=[])

        # Negative attribute ("không X", "ít X") → no_result when none of top-K match
        has_negative_attr = any(_NEGATIVE_ATTR_RE.match(a) for a in extraction.attributes)
        if has_negative_attr:
            attr_match_count = sum(1 for r in scored_rows[:5] if r.audit.attributes_ratio > 0)
            if attr_match_count == 0:
                return Decision(type="no_result", confidence=0.80, reason="negative_attr_no_match", items=[])

        if (
            top.structural_score < self.cfg.min_relevance_score
            and top.audit.specified_count == 0
        ):
            no_result_conf = self._sigmoid((self.cfg.min_relevance_score - top.structural_score) / 5.0)
            return Decision(type="no_result", confidence=round(no_result_conf, 2), reason="low_relevance_unstructured", items=[])

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
            items=self._top_3_diverse(scored_rows, extraction.product_name or ""),
        )

    def _top_3_diverse(self, rows: list[ScoredRow], query_text: str = "") -> list[ScoredRow]:
        # Last-line variant guard: if user did not mention any variant keyword,
        # filter out products containing variant tokens before diverse-pick.
        query_lower = query_text.lower()
        if not any(vt in query_lower for vt in VARIANT_TOKENS):
            filtered = [r for r in rows if not any(vt in r.product.get("name", "").lower() for vt in VARIANT_TOKENS)]
            if filtered:
                rows = filtered
            # else: fallback to original rows if filtering would leave nothing

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
