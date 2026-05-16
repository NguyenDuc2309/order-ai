from dataclasses import asdict, dataclass
from enum import Enum
import re

from app.core.config import SIZE_HINTS
from app.core.logging_config import setup_audit_logger
from app.models.extraction import ExtractionResult
from app.utils.normalizer import normalize_brand, normalize_category, normalize_packaging, normalize_token
from app.utils.unit_converter import value_to_ml


class MatchState(str, Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    PARTIAL = "partial"
    NOT_SPECIFIED = "not_specified"


@dataclass
class AuditResult:
    brand: MatchState
    category: MatchState
    size: MatchState
    packaging: MatchState
    attributes: MatchState
    attributes_ratio: float
    must_not: MatchState
    qty_extracted: int
    hard_pass: bool
    soft_pass: bool
    satisfied_count: int
    specified_count: int


class ConstraintAuditor:
    """Đánh giá mức độ khớp giữa ExtractionResult và 1 product từ ES.

    Mỗi constraint (brand, category, size, packaging, attributes, must_not) được
    đánh giá độc lập ra MatchState. Kết quả AuditResult được dùng bởi StructuralScorer
    (tính điểm) và Decider (AND gate cho exact_match).

    Không có side-effect ngoài structured log. Có thể gọi nhiều lần cho nhiều products.
    """

    def __init__(self) -> None:
        self.logger = setup_audit_logger()

    def audit(self, extraction: ExtractionResult, product: dict) -> AuditResult:
        """Audit 1 product so với extraction constraints.

        Args:
            extraction: Kết quả từ GeminiParser (brand, category, size, must_not, …)
            product: Dict từ ES hit (_source)

        Returns:
            AuditResult với MatchState cho mỗi field và hard_pass/soft_pass summary.
        """
        satisfied_count = 0
        specified_count = 0

        brand_state = MatchState.NOT_SPECIFIED
        if extraction.brand:
            specified_count += 1
            product_brand = normalize_brand(str(product.get("brand_norm") or product.get("brand") or ""))
            wanted_brand = normalize_brand(extraction.brand)
            if wanted_brand and wanted_brand == product_brand:
                brand_state = MatchState.MATCH
                satisfied_count += 1
            else:
                brand_state = MatchState.MISMATCH

        category_state = MatchState.NOT_SPECIFIED
        if extraction.category:
            specified_count += 1
            extracted_category = normalize_category(extraction.category)
            product_category = normalize_category(
                str(product.get("category_norm") or product.get("category") or "")
            )
            if extracted_category and extracted_category == product_category:
                category_state = MatchState.MATCH
                satisfied_count += 1
            else:
                category_state = MatchState.MISMATCH

        has_size_constraint = extraction.size_value is not None or extraction.size_hint is not None
        size_state = MatchState.NOT_SPECIFIED
        if has_size_constraint:
            specified_count += 1
            if self._size_match(product, extraction):
                size_state = MatchState.MATCH
                satisfied_count += 1
            else:
                size_state = MatchState.MISMATCH

        packaging_state = MatchState.NOT_SPECIFIED
        if extraction.unit_raw:
            specified_count += 1
            lhs = normalize_packaging(extraction.unit_raw)
            rhs = normalize_packaging(str(product.get("packaging", "")))
            if lhs == rhs:
                packaging_state = MatchState.MATCH
                satisfied_count += 1
            else:
                packaging_state = MatchState.MISMATCH

        attrs_state = MatchState.NOT_SPECIFIED
        attributes_ratio = 0.0
        if extraction.attributes:
            specified_count += 1
            total = len(extraction.attributes)
            tags = {str(tag).lower() for tag in product.get("tags", [])}
            haystack = f"{product.get('name', '')} {product.get('base_name', '')}".lower()
            matched_count = 0
            for attr in extraction.attributes:
                raw = attr.lower().strip()
                candidates = {raw, raw.replace("_", " "), re.sub(r"^(size|is)_", "", raw)}
                if tags & candidates or any(c in haystack for c in candidates if c):
                    matched_count += 1
            attributes_ratio = matched_count / total if total > 0 else 0.0
            if attributes_ratio >= 1.0:
                attrs_state = MatchState.MATCH
                satisfied_count += 1
            elif attributes_ratio > 0.0:
                attrs_state = MatchState.PARTIAL
            else:
                attrs_state = MatchState.MISMATCH

        must_not_state = MatchState.NOT_SPECIFIED
        if extraction.must_not:
            specified_count += 1
            haystack = normalize_token(str(product.get("name", "")))
            forbidden = [normalize_token(token) for token in extraction.must_not if token.strip()]
            violated = any(token and token in haystack for token in forbidden)
            if violated:
                must_not_state = MatchState.MISMATCH
            else:
                must_not_state = MatchState.MATCH
                satisfied_count += 1

        hard_pass = (
            brand_state in (MatchState.MATCH, MatchState.NOT_SPECIFIED)
            and category_state in (MatchState.MATCH, MatchState.NOT_SPECIFIED)
            and must_not_state in (MatchState.MATCH, MatchState.NOT_SPECIFIED)
        )
        soft_pass = hard_pass and (
            size_state in (MatchState.MATCH, MatchState.NOT_SPECIFIED)
            and packaging_state in (MatchState.MATCH, MatchState.NOT_SPECIFIED)
        )

        result = AuditResult(
            brand=brand_state,
            category=category_state,
            size=size_state,
            packaging=packaging_state,
            attributes=attrs_state,
            attributes_ratio=attributes_ratio,
            must_not=must_not_state,
            qty_extracted=max(1, extraction.quantity),
            hard_pass=hard_pass,
            soft_pass=soft_pass,
            satisfied_count=satisfied_count,
            specified_count=specified_count,
        )
        self.logger.info(
            "constraint_audit",
            extra={"event": {"product_name": product.get("name", ""), "audit": self.to_dict(result)}},
        )
        return result

    @staticmethod
    def to_dict(result: AuditResult) -> dict:
        payload = asdict(result)
        for key in ("brand", "category", "size", "packaging", "attributes", "must_not"):
            payload[key] = payload[key].value
        return payload

    @staticmethod
    def _size_match(product: dict, extraction: ExtractionResult) -> bool:
        prod_ml = float(product.get("size_value_ml") or 0.0)
        if prod_ml == 0.0:
            prod_ml = value_to_ml(float(product.get("size_value") or 0.0), product.get("size_unit"))

        if extraction.size_value is not None and extraction.size_unit is not None:
            ext_ml = value_to_ml(float(extraction.size_value), extraction.size_unit)
            tolerance = max(prod_ml * 0.08, 20.0)
            return abs(prod_ml - ext_ml) <= tolerance

        if extraction.size_hint is None:
            return False

        # Look up category-specific thresholds; fall back to _default
        cat_key = normalize_category(str(product.get("category_norm") or product.get("category") or ""))
        hint_cfg = SIZE_HINTS.get(cat_key) or SIZE_HINTS["_default"]
        large_thresh = hint_cfg["large"]
        small_thresh = hint_cfg["small"]

        if extraction.size_hint == "large":
            return prod_ml >= large_thresh
        if extraction.size_hint == "small":
            return prod_ml <= small_thresh
        return small_thresh < prod_ml < large_thresh
