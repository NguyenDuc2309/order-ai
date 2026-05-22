from app.models.extraction import ExtractionResult
from app.prompts.loader import load_prompt
from app.core.clients.gemini import GeminiClient
from app.services.extractor.interface import BaseExtractor
from app.services.ranker.rules import apply_defaults
from app.utils.text_norm import normalize_text


class GeminiParser(BaseExtractor):
    def __init__(self, gemini_client: GeminiClient | None = None) -> None:
        self.gemini_client = gemini_client or GeminiClient()
        prompt_payload = load_prompt("extraction_v1.yaml")
        self.system_prompt = prompt_payload["system"]

    def extract(self, query: str) -> ExtractionResult:
        text = normalize_text(query)
        raw = self.gemini_client.generate_json(self.system_prompt, text)
        raw = self._normalize_raw(raw, fallback_name=text)
        result = ExtractionResult(**raw)
        return apply_defaults(result)

    def _normalize_raw(self, raw: dict | list, fallback_name: str = "") -> dict:
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, list):
            for item in raw:
                if isinstance(item, dict):
                    return item
        return self._fallback_extract(fallback_name)

    def _fallback_extract(self, query_text: str = "") -> dict:
        # Use the raw query as product_name so ES can still attempt BM25 search.
        return {
            "product_name": query_text.strip() or "",
            "unit_raw": None,
            "size_value": None,
            "size_unit": None,
            "size_hint": None,
            "attributes": [],
            "must_not": [],
        }
