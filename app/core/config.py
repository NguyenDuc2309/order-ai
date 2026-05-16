import os
from dataclasses import dataclass, field
from typing import Dict

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Settings:
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    embedding_model: str = os.getenv("EMBEDDING_MODEL", "text-embedding-004")
    elastic_url: str = os.getenv("ELASTIC_URL", "http://localhost:9200")
    elastic_index: str = os.getenv("ELASTIC_INDEX", "products")
    elastic_verify_certs: bool = os.getenv("ELASTIC_VERIFY_CERTS", "false").lower() == "true"


settings = Settings()


@dataclass
class RankerConfig:
    min_relevance_score: float = 30.0
    gap_exact_threshold: int = 20
    gap_exact_threshold_strict: int = 40
    gap_exact_threshold_explicit: int = 10
    weight_brand_match: float = 100.0
    weight_brand_miss: float = -50.0
    weight_category_match: float = 50.0
    weight_category_miss: float = -20.0
    weight_size_match: float = 30.0
    weight_size_miss: float = -40.0
    weight_packaging_match: float = 10.0
    weight_packaging_miss: float = -20.0
    weight_attribute: float = 10.0
    weight_best_seller: float = 1.0
    weight_variant_penalty: float = 50.0


# Per-category size-hint thresholds (ml for liquids, g for dry goods).
# Keys are normalised category_norm values. "_default" is the fallback.
SIZE_HINTS: Dict[str, Dict[str, float]] = {
    "beverage_bottle":     {"large": 1000.0, "small": 350.0},
    "beverage_can":        {"large": 500.0,  "small": 250.0},
    "instant_noodle_pack": {"large": 100.0,  "small": 75.0},   # grams
    "snack":               {"large": 200.0,  "small": 50.0},   # grams
    "_default":            {"large": 1000.0, "small": 350.0},
}


@dataclass
class AppConfig:
    ranker: RankerConfig = field(default_factory=RankerConfig)


config = AppConfig()
