import math
from dataclasses import dataclass
from typing import Literal

from app.core.config import config
from app.models.extraction import ExtractionResult
from app.services.ranker.constraint_audit import MatchState
from app.services.ranker.scorer import ScoredRow, _has_variant_token, _query_mentions_variant
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

        # no_result gate: user đã specify ít nhất 1 constraint nhưng không constraint nào
        # được thỏa bởi top-1. Đây là tín hiệu rõ ràng catalog không có sản phẩm phù hợp.
        # Không cần điều kiện score vì brand/category MISMATCH đã trừ điểm nặng (-50/-20);
        # giữ điều kiện score như backup cho trường hợp specified_count=0 (query không có constraint).
        if top.audit.satisfied_count == 0 and top.audit.specified_count >= 1:
            return Decision(type="no_result", confidence=0.95, reason="no_constraint_satisfied", items=[])

        # Brand MISMATCH + ít constraint thỏa → likely OOC.
        # Bỏ score threshold: kNN có thể kéo score lên cao dù brand hoàn toàn sai (P1).
        if (
            top.audit.brand == MatchState.MISMATCH
            and top.audit.satisfied_count <= 1
        ):
            return Decision(type="no_result", confidence=0.85, reason="brand_mismatch_unresolvable", items=[])

        # Attribute constraint (bất kỳ loại nào: "có ga", "không cồn", "rửa mặt"…)
        # không được thỏa bởi bất kỳ sản phẩm nào trong top-5 → catalog không có.
        if extraction.attributes:
            attr_match_count = sum(1 for r in scored_rows[:5] if r.audit.attributes_ratio > 0)
            if attr_match_count == 0:
                return Decision(type="no_result", confidence=0.80, reason="attr_no_match", items=[])

        # Product-name bigram coverage gate (fallback khi brand=null, attributes=[], must_not=[]).
        # Nếu không có constraint nào khác và product_name gồm ≥2 từ nhưng không bigram nào
        # xuất hiện trong tên top-5 sản phẩm → catalog không có sản phẩm khớp.
        if not extraction.brand and not extraction.attributes and not extraction.must_not:
            pname_words = (extraction.product_name or "").lower().split()
            if len(pname_words) >= 2:
                bigrams = [f"{pname_words[i]} {pname_words[i+1]}" for i in range(len(pname_words) - 1)]
                top5_names = [r.product.get("name", "").lower() for r in scored_rows[:5]]
                if not any(bg in name for name in top5_names for bg in bigrams):
                    return Decision(type="no_result", confidence=0.72, reason="product_name_not_covered", items=[])

        if (
            top.structural_score < self.cfg.min_relevance_score
            and top.audit.specified_count == 0
        ):
            no_result_conf = self._sigmoid((self.cfg.min_relevance_score - top.structural_score) / 5.0)
            return Decision(type="no_result", confidence=round(no_result_conf, 2), reason="low_relevance_unstructured", items=[])

        gap_required = self.cfg.gap_exact_threshold if top.audit.soft_pass else self.cfg.gap_exact_threshold_strict
        is_specific = bool(extraction.brand) or bool(extraction.unit_raw) or bool(extraction.size_value)
        if is_specific:
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
        if not _query_mentions_variant(query_text.lower()):
            filtered = [r for r in rows if not _has_variant_token(r.product.get("name", "").lower())]
            if filtered:
                rows = filtered
            # else: fallback to original rows if filtering would leave nothing

        if len(rows) <= 3:
            return rows
        # Pick diverse by size: highest score (rows[0]), largest, smallest
        top = rows[0]
        largest = max(rows, key=lambda row: value_to_ml(row.product.get("size_value"), row.product.get("size_unit")))
        smallest = min(rows, key=lambda row: value_to_ml(row.product.get("size_value"), row.product.get("size_unit")))
        picked: list[ScoredRow] = []
        seen: set[str] = set()
        for cand in (top, largest, smallest):
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
