from app.models.extraction import ExtractionResult
from app.utils.unit_converter import value_to_ml


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

        # 2. Hard size filter — applied at ES level to cut candidate pool
        filter_clauses: list[dict] = []
        if extracted.size_value is not None and extracted.size_unit is not None:
            prod_ml = value_to_ml(extracted.size_value, extracted.size_unit)
            # ±8% tolerance to handle minor indexing discrepancies
            tolerance = max(prod_ml * 0.08, 15.0)
            filter_clauses.append({
                "range": {
                    "size_value_ml": {
                        "gte": prod_ml - tolerance,
                        "lte": prod_ml + tolerance,
                    }
                }
            })

        # 3. Soft boosting — brand keyword (exact) + category + packaging
        should_clauses: list[dict] = []
        if extracted.brand:
            # brand is a keyword field → exact lowercase match
            should_clauses.append({"term": {"brand": {"value": extracted.brand.lower(), "boost": 60}}})
        if extracted.category:
            should_clauses.append({"term": {"category": {"value": extracted.category, "boost": 30}}})
        if extracted.unit_raw:
            should_clauses.append({"term": {"packaging": {"value": extracted.unit_raw.lower(), "boost": 20}}})

        # 4. Must-not — exclude across all searchable text + tags keyword field
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
                "filter": filter_clauses
            },
            "query": {
                "bool": {
                    "must": must_clauses,
                    "filter": filter_clauses,
                    "should": should_clauses,
                    "must_not": must_not_clauses,
                }
            }
        }
