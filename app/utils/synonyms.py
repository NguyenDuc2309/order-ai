import re

SYNONYM_MAP = {
    "bò húc": "red bull",
    "bo huc": "red bull",
    "nước suối": "water",
    "nuoc suoi": "water",
    "sữa tươi": "milk",
    "sua tuoi": "milk",
    "nước ngọt": "soft drink",
    "nuoc ngot": "soft drink",
    "bia": "beer",
    "hộp": "hop",
    "thùng": "thung",
    "lốc": "loc",
    "két": "ket",
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
