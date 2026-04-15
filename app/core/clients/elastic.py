from elasticsearch import Elasticsearch

from app.core.config import settings


_client: Elasticsearch | None = None


def get_client() -> Elasticsearch:
    global _client
    if _client is None:
        _client = Elasticsearch(
            settings.elastic_url,
            verify_certs=settings.elastic_verify_certs,
            request_timeout=30,
        )
    return _client
