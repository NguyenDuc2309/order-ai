import logging
from app.models.extraction import ExtractionResult
from app.utils.unit_converter import value_to_ml

logger = logging.getLogger("orderresolve.scoring")

class ScoringRanker:
    def score(self, rows: list[dict], extraction: ExtractionResult) -> list[dict]:
        scored: list[dict] = []
        
        for row in rows:
            product = row["product"]
            es_score = float(row.get("score", 0.0))
            
            # Base Score
            final_score = es_score
            
            # 1. Brand Match (Deterministic Hard Rule)
            brand_match = False
            if extraction.brand:
                if str(product.get("brand", "")).lower() == extraction.brand.lower():
                    final_score += 100.0
                    brand_match = True
                else:
                    final_score -= 50.0
            
            # 2. Category Match (Hard Rule)
            cat_match = False
            if extraction.category:
                if str(product.get("category", "")).lower() == extraction.category.lower():
                    final_score += 50.0
                    cat_match = True
                else:
                    final_score -= 20.0
            
            # 3. Size & Unit Match (Hard Rule)
            size_match = self.size_match(product, extraction)
            unit_match = (not extraction.unit_raw) or (product.get("packaging") == extraction.unit_raw)
            
            if (extraction.size_value or extraction.size_hint):
                if size_match:
                    final_score += 30.0
                else:
                    final_score -= 40.0
            
            if extraction.unit_raw:
                if unit_match:
                    final_score += 10.0
                else:
                    final_score -= 20.0

            # 4. Attributes (Zero, Diet, etc.)
            attr_count = self._attribute_match_count(product, extraction)
            final_score += attr_count * 10.0

            # 5. Best Seller tie-breaker
            if bool(product.get("is_best_seller")):
                final_score += 1.0

            final_score = round(max(0.01, final_score), 4)
            
            logger.debug(
                "Product: %s | Brand Match: %s | Size Match: %s | Final Score: %.2f",
                product["name"], brand_match, size_match, final_score
            )
            
            scored.append({**row, "score": final_score})

        return sorted(scored, key=lambda item: item["score"], reverse=True)

    def size_match(self, product: dict, extraction: ExtractionResult) -> bool:
        if extraction.size_value is not None and extraction.size_unit is not None:
            prod_ml = value_to_ml(float(product.get("size_value", 0.0)), product.get("size_unit"))
            ext_ml = value_to_ml(float(extraction.size_value), extraction.size_unit)
            return abs(prod_ml - ext_ml) < 50.0

        if extraction.size_hint is None:
            return False

        size_ml = value_to_ml(float(product.get("size_value", 0.0)), product.get("size_unit"))
        if extraction.size_hint == "large": return size_ml >= 1000
        if extraction.size_hint == "small": return size_ml <= 350
        return 350 < size_ml < 1000

    def _attribute_match_count(self, product: dict, extraction: ExtractionResult) -> int:
        if not extraction.attributes: return 0
        tags = {str(tag).lower() for tag in product.get("tags", [])}
        haystack = f"{product.get('name', '')} {product.get('base_name', '')}".lower()
        count = 0
        for attr in extraction.attributes:
            normalized = attr.lower().replace("_", " ")
            if attr.lower() in tags or normalized in haystack: count += 1
            else: count -= 1
        return count
