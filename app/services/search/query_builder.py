from app.models.extraction import ExtractionResult


class QueryBuilder:
    def build(self, extracted: ExtractionResult, query_vector: list[float]) -> dict:
        # 1. BM25 — search across all text fields; base_name and brand_display are analyzed text
        must_clauses: list[dict] = [
            {
                "multi_match": {
                    "query": extracted.product_name,
                    "fields": ["base_name^4", "name^3", "brand_display^3", "mch_path^2", "tags"],
                    "fuzziness": "AUTO",
                    "type": "best_fields",
                }
            }
        ]

        # 2. Soft boosting — brand_norm keyword (exact) + category_norm + packaging
        # Size is intentionally NOT filtered here — StructuralScorer handles size match/penalty
        # so ES recall stays high and only post-retrieval scoring cuts wrong sizes.
        should_clauses: list[dict] = []
        if extracted.brand:
            should_clauses.append({"term": {"brand_norm": {"value": extracted.brand.lower(), "boost": 60}}})
        if extracted.category:
            should_clauses.append({"term": {"category_norm": {"value": extracted.category.lower(), "boost": 30}}})
        if extracted.unit_raw:
            should_clauses.append({"term": {"packaging": {"value": extracted.unit_raw.lower(), "boost": 20}}})

        # 3. Must-not — exclude across all searchable text + tags keyword field
        must_not_clauses: list[dict] = []
        for keyword in extracted.must_not:
            must_not_clauses.append({
                "multi_match": {
                    "query": keyword,
                    "fields": ["name", "base_name", "mch_path"],
                }
            })
            # Also exclude via tags keyword (exact match)
            must_not_clauses.append({"term": {"tags": keyword.lower()}})

        return {
            "size": 20,
            "knn": {
                "field": "name_vector",
                "query_vector": query_vector,
                "k": 20,
                "num_candidates": 200,  # ES recommends >= 10*k for quality
            },
            "query": {
                "bool": {
                    "must": must_clauses,
                    "should": should_clauses,
                    "must_not": must_not_clauses,
                }
            }
        }
