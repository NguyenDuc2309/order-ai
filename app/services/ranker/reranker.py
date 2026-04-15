from app.core.clients.gemini import GeminiClient
from app.models.extraction import ExtractionResult
from app.prompts.loader import load_prompt


class GeminiReranker:
    def __init__(self, gemini_client: GeminiClient) -> None:
        self.gemini_client = gemini_client
        prompt_payload = load_prompt("reranking_v1.yaml")
        self.system_prompt = prompt_payload["system"]

    def rerank(self, query: str, extraction: ExtractionResult, hits: list[dict]) -> dict:
        """
        Calls Gemini to evaluate how well the top hits match the original query and extraction.
        Returns a JSON with confidence scores and rationales.
        """
        if not hits:
            return {"top_confidence": 0.0, "ranked_items": []}

        # Prepare context for Gemini
        context = {
            "original_query": query,
            "extraction": extraction.model_dump(),
            "hits": [
                {
                    "id": h["product"]["id"],
                    "name": h["product"]["name"],
                    "packaging": h["product"].get("packaging"),
                    "size": f"{h['product'].get('size_value')} {h['product'].get('size_unit')}",
                    "tags": h["product"].get("tags", []),
                }
                for h in hits
            ],
        }

        try:
            result = self.gemini_client.generate_json(self.system_prompt, str(context))
            return result
        except Exception:
            # Fallback if LLM fails
            return {"top_confidence": 0.5, "ranked_items": []}
