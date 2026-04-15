import os
from dataclasses import dataclass

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
