import re
from dataclasses import dataclass

from app.core.config import config
from app.models.extraction import ExtractionResult
from app.services.ranker.constraint_audit import ConstraintAuditor, AuditResult, MatchState

# Tokens that signal a "special variant" — if user did not mention any of these,
# products containing them are penalised (variant hallucination guard).
# Multi-word tokens (Vietnamese phrases) are matched as substrings; single-word tokens
# are matched at word boundaries to prevent false positives.
VARIANT_TOKENS = {
    "light", "zero", "diet", "không đường", "không calo",
    "tách béo", "ít béo", "không béo",
    "crystal", "silver", "không cồn", "lite",
    "sparkling",
}

_SINGLE_WORD_VARIANT_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in VARIANT_TOKENS if " " not in t) + r")\b",
    re.IGNORECASE,
)
_MULTI_WORD_VARIANTS = [t for t in VARIANT_TOKENS if " " in t]


def _has_variant_token(text: str) -> bool:
    """Return True if text contains any variant token (word-boundary for single words)."""
    if _SINGLE_WORD_VARIANT_RE.search(text):
        return True
    return any(t in text for t in _MULTI_WORD_VARIANTS)


def _query_mentions_variant(query: str) -> bool:
    """Return True if the user query itself mentions a variant keyword."""
    return _has_variant_token(query)


@dataclass
class ScoredRow:
    product: dict
    raw_es_score: float
    structural_score: float
    audit: AuditResult


class StructuralScorer:
    """Tính structural score cho mỗi ES hit dựa trên ConstraintAuditor kết quả.

    Score = raw_es_score + weighted audit results (brand, category, size, packaging, attrs).
    Weights được config trong RankerConfig. Sort desc theo structural_score (stable).

    Deterministic — cùng input luôn cho cùng output. Không gọi LLM hoặc ES.
    """

    def __init__(self) -> None:
        self.auditor = ConstraintAuditor()
        self.cfg = config.ranker

    def score(self, rows: list[dict], extraction: ExtractionResult) -> list[ScoredRow]:
        """Score và sort tất cả rows.

        Args:
            rows: List ES hits, mỗi item là {"product": {...}, "score": float}
            extraction: ExtractionResult từ GeminiParser

        Returns:
            List ScoredRow sorted by structural_score desc (ties giữ ES order).
        """
        scored: list[ScoredRow] = []
        for idx, row in enumerate(rows):
            product = row["product"]
            raw_es_score = float(row.get("score", 0.0))
            audit = self.auditor.audit(extraction, product)

            structural_score = raw_es_score
            structural_score += self._weight_match(audit.brand, self.cfg.weight_brand_match, self.cfg.weight_brand_miss)
            structural_score += self._weight_match(
                audit.category, self.cfg.weight_category_match, self.cfg.weight_category_miss
            )
            structural_score += self._weight_match(audit.size, self.cfg.weight_size_match, self.cfg.weight_size_miss)
            structural_score += self._weight_match(
                audit.packaging, self.cfg.weight_packaging_match, self.cfg.weight_packaging_miss
            )
            structural_score += (audit.attributes_ratio * len(extraction.attributes)) * self.cfg.weight_attribute

            # Variant penalty: if the user did NOT mention any variant keyword,
            # penalise products whose name contains a variant token.
            query_lower = (extraction.product_name or "").lower()
            if not _query_mentions_variant(query_lower):
                product_name_lower = product.get("name", "").lower()
                if _has_variant_token(product_name_lower):
                    structural_score -= self.cfg.weight_variant_penalty

            scored.append(
                ScoredRow(
                    product=product,
                    raw_es_score=raw_es_score,
                    structural_score=round(max(0.01, structural_score), 4),
                    audit=audit,
                )
            )

        # stable: ties keep ES order via index fallback
        ranked = sorted(enumerate(scored), key=lambda pair: (-pair[1].structural_score, pair[0]))
        return [pair[1] for pair in ranked]

    @staticmethod
    def _weight_match(state: MatchState, plus: float, minus: float) -> float:
        if state == MatchState.MATCH:
            return plus
        if state == MatchState.MISMATCH:
            return minus
        return 0.0
