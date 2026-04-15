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
                        "base_name": source.get("base_name"),
                        "size_value": source.get("size_value"),
                        "size_unit": source.get("size_unit"),
                        "packaging": source.get("packaging"),
                        "tags": source.get("tags", []),
                        "is_best_seller": source.get("is_best_seller", False),
                    },
                    "score": float(hit.get("_score", 0.0)),
                }
            )
        return rows
