import logging
import time
from concurrent.futures import ThreadPoolExecutor

from app.graph.state import SearchState
from app.core.clients.gemini import GeminiClient
from app.services.extractor.gemini_parser import GeminiParser
from app.services.ranker.engine import RankingEngine
from app.services.search.es_service import ElasticsearchService
from app.services.search.query_builder import QueryBuilder
from app.utils.synonyms import normalize_query_text

gemini_client = GeminiClient()
extractor = GeminiParser(gemini_client=gemini_client)
query_builder = QueryBuilder()
es_service = ElasticsearchService()
ranking_engine = RankingEngine()
logger = logging.getLogger("orderresolve.pipeline")


def extract_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[extract_node] start query=%s", state["query"])
    
    # 1. Hard synonym replacement before any processing
    query_text = normalize_query_text(state["query"])
    
    # 2. Extract entities and embed in parallel
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_extract = pool.submit(extractor.extract, query_text)
        future_embed = pool.submit(gemini_client.embed_text, query_text)
        extraction = future_extract.result()
        query_vector = future_embed.result()
    
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info("[extract_node] done in %.2fms", elapsed)
    return {"extraction": extraction, "query_vector": query_vector}


def build_query_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[build_query_node] start")
    es_query = query_builder.build(state["extraction"], state["query_vector"])
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info("[build_query_node] done in %.2fms", elapsed)
    return {"es_query": es_query}


def search_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[search_node] start")
    
    rows = es_service.search(state["es_query"])
    
    # Note: QueryBuilder already uses soft filters for Packaging/Category
    # so recall is naturally high.
        
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info("[search_node] done in %.2fms hits=%s", elapsed, len(rows))
    return {"hits": rows}


def decide_node(state: SearchState) -> dict:
    start_time = time.perf_counter()
    logger.info("[decide_node] start")
    response = ranking_engine.decide(
        extracted=state["extraction"], 
        rows=state["hits"],
        original_query=state["query"]
    )
    elapsed = (time.perf_counter() - start_time) * 1000
    logger.info("[decide_node] done in %.2fms status=%s", elapsed, response.status)
    return {"response": response}
