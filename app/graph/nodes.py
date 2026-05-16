import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.graph.state import SearchState
from app.core.clients.gemini import GeminiClient
from app.core.logging_config import setup_audit_logger
from app.utils.normalizer import normalize_brand
from app.utils.synonyms import resolve_brand_alias
from app.services.extractor.gemini_parser import GeminiParser
from app.services.ranker.engine import RankingEngine
from app.services.search.es_service import ElasticsearchService
from app.services.search.query_builder import QueryBuilder

gemini_client = GeminiClient()
extractor = GeminiParser(gemini_client=gemini_client)
query_builder = QueryBuilder()
es_service = ElasticsearchService()
ranking_engine = RankingEngine()
logger = logging.getLogger("orderresolve.pipeline")
audit_logger = setup_audit_logger()


def extract_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[extract_node] start query=%s", state["query"])
    
    query_text = state["query"]

    # Extract entities and embed in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_extract = pool.submit(extractor.extract, query_text)
        future_embed = pool.submit(gemini_client.embed_text, query_text)
        extraction = future_extract.result()
        query_vector = future_embed.result()

    raw_brand = extraction.brand
    alias_brand = resolve_brand_alias(raw_brand) if raw_brand else raw_brand
    normalized_brand = normalize_brand(alias_brand) if alias_brand else alias_brand
    if extraction.brand:
        extraction.brand = normalized_brand
    
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info(
        "[extract_node] done in %.2fms output_size=%s brand_resolution=%s",
        elapsed,
        len(query_vector),
        {"raw": raw_brand, "alias": alias_brand, "normalized": normalized_brand},
    )
    return {"extraction": extraction, "query_vector": query_vector}


def build_query_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[build_query_node] start")
    es_query = query_builder.build(state["extraction"], state["query_vector"])
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info("[build_query_node] done in %.2fms output_size=%s", elapsed, len(str(es_query)))
    return {"es_query": es_query}


def search_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[search_node] start")
    
    rows = es_service.search(state["es_query"])
    
    # Note: QueryBuilder already uses soft filters for Packaging/Category
    # so recall is naturally high.
        
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info("[search_node] done in %.2fms output_size=%s", elapsed, len(rows))
    return {"hits": rows}


def decide_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[decide_node] start")
    response = ranking_engine.decide(
        extracted=state["extraction"], 
        rows=state["hits"],
        original_query=state["query"]
    )
    audit_logger.info(
        "ranking_decision",
        extra={
            "event": {
                "query": state["query"],
                "decision_type": response.type,
                "confidence": response.confidence,
                "items": [item.model_dump() for item in response.items],
            }
        },
    )
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info(
        "[decide_node] done in %.2fms status=%s output_size=%s",
        elapsed,
        response.status,
        len(response.items),
    )
    return {"response": response}
