import json

from cachetools import TTLCache
from google import genai
from google.genai import types

from app.core.config import settings

_embed_cache: TTLCache = TTLCache(maxsize=2000, ttl=3600)


class GeminiClient:
    def __init__(self) -> None:
        self.api_key = settings.gemini_api_key
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None

    def generate_json(self, system_prompt: str, user_input: str) -> dict:
        if self.client is None:
            raise RuntimeError("GEMINI_API_KEY is missing")

        response = self.client.models.generate_content(
            model=settings.gemini_model,
            contents=f"{system_prompt}\n\nInput:\n{user_input}",
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.1,
            ),
        )
        text = (response.text or "").strip()
        return self._parse_json(text)

    def embed_text(self, text: str) -> list[float]:
        if self.client is None:
            raise RuntimeError("GEMINI_API_KEY is missing")
        key = text.strip().lower()
        if key in _embed_cache:
            return _embed_cache[key]
        
        # text-embedding-004 allows setting dimensionality
        embed_config = {}
        if "text-embedding-004" in settings.embedding_model:
            embed_config["output_dimensionality"] = 768

        result = self.client.models.embed_content(
            model=settings.embedding_model,
            contents=text,
            config=types.EmbedContentConfig(**embed_config) if embed_config else None
        )
        if not result.embeddings:
            return []
        vector = list(result.embeddings[0].values)
        _embed_cache[key] = vector
        return vector

    def _parse_json(self, content: str) -> dict:
        cleaned = content.strip()
        if not cleaned:
            return {}
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.startswith("json"):
                cleaned = cleaned[4:].strip()
        return json.loads(cleaned)
