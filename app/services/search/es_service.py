from app.core.clients.elastic import get_client
from app.core.config import settings


class ElasticsearchService:
    def __init__(self) -> None:
        self.client = get_client()

    def search(self, query_payload: dict) -> list[dict]:
        result = self.client.search(index=settings.elastic_index, body=query_payload)
        hits = result.get("hits", {}).get("hits", [])
        rows: list[dict] = []
        for hit in hits:
            source = hit.get("_source", {})
            rows.append(
                {
                    "product": {
                        "id": source.get("id", hit.get("_id")),
                        "name": source.get("name"),
                        "base_name": source.get("base_name") or source.get("name"),
                        "brand": source.get("brand", ""),
                        "category": source.get("category", ""),
                        "size_value": source.get("size_value"),
                        "size_unit": source.get("size_unit"),
                        "size_value_ml": source.get("size_value_ml"),
                        "packaging": source.get("packaging"),
                        "pack_count": source.get("pack_count", 1),
                        "tags": source.get("tags", []),
                        "is_best_seller": source.get("is_best_seller", False),
                        "sale_price": source.get("sale_price", 0.0),
                        "image": source.get("image", ""),
                    },
                    "score": float(hit.get("_score", 0.0)),
                }
            )
        return rows
