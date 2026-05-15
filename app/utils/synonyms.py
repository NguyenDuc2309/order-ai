import re

SYNONYM_MAP = {
    # Slang / brand aliases
    "bò húc": "red bull",
    "bo huc": "red bull",
    # Generic category terms → normalized English for BM25 + extraction
    "nước suối": "water",
    "nuoc suoi": "water",
    "sữa tươi": "milk",
    "sua tuoi": "milk",
    "nước ngọt": "soft drink",
    "nuoc ngot": "soft drink",
    "bia": "beer",
    # NOTE: packaging units (thùng, hộp, lốc, két) are intentionally NOT mapped here.
    # They must be preserved in Vietnamese so Gemini can extract unit_raw correctly.
}

def normalize_query_text(text: str) -> str:
    """
    Hard replacement of synonyms to ensure deterministic search.
    """
    lowered = text.lower()
    for token, replacement in SYNONYM_MAP.items():
        # Use regex for word boundaries to avoid partial matches
        pattern = rf"\b{re.escape(token)}\b"
        lowered = re.sub(pattern, replacement, lowered)
    
    return lowered
