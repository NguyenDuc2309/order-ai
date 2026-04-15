from app.models.extraction import ExtractionResult
from app.utils.unit_converter import value_to_ml


class QueryBuilder:
    def build(self, extracted: ExtractionResult, query_vector: list[float]) -> dict:
        # 1. Base Logic (BM25 - Text Match)
        must_clauses: list[dict] = [
            {
                "multi_match": {
                    "query": extracted.product_name,
                    "fields": ["base_name^5", "name^3", "brand^3", "tags"],
                    "fuzziness": "AUTO",
                }
            }
        ]
        
        # 2. Hard Filters (Strict Constraints)
        filter_clauses: list[dict] = []
        
        # Volume is usually a hard constraint
        if extracted.size_value is not None and extracted.size_unit is not None:
            prod_ml = value_to_ml(extracted.size_value, extracted.size_unit)
            tolerance = prod_ml * 0.05 # Increased to 5%
            filter_clauses.append({
                "range": {
                    "size_value_ml": {
                        "gte": prod_ml - tolerance,
                        "lte": prod_ml + tolerance
                    }
                }
            })
            
        # 3. Soft Boosting (Should Clauses) - RECALL IMPROVEMENT
        # Move Packaging and Category to Should to avoid empty results
        should_clauses: list[dict] = []
        
        if extracted.brand:
            should_clauses.append({"term": {"brand": {"value": extracted.brand.lower(), "boost": 50}}})
            
        if extracted.category:
            should_clauses.append({"term": {"category": {"value": extracted.category.lower(), "boost": 30}}})
            
        if extracted.unit_raw:
            should_clauses.append({"term": {"packaging": {"value": extracted.unit_raw.lower(), "boost": 20}}})

        # Must Not (Exclusion)
        must_not_clauses: list[dict] = []
        for keyword in extracted.must_not:
            must_not_clauses.append({"match": {"name": keyword}})

        return {
            "size": 20,
            "knn": {
                "field": "name_vector",
                "query_vector": query_vector,
                "k": 20,
                "num_candidates": 100,
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
