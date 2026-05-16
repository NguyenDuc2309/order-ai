import re
import unicodedata


_BRAND_PUNCT_RE = re.compile(r"[-_./]+")
_SPACE_RE = re.compile(r"\s+")

_PACKAGING_MAP = {
    "lon": "can",
    "can": "can",
    "chai": "bottle",
    "bottle": "bottle",
    "thung": "case",
    "thùng": "case",
    "case": "case",
    "hop": "box",
    "hộp": "box",
    "box": "box",
    "goi": "pack",
    "gói": "pack",
    "pack": "pack",
    "ly": "cup",
    "cup": "cup",
}


def _strip_diacritics(s: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", s or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_token(s: str | None) -> str:
    base = _strip_diacritics(s).lower().strip()
    return _SPACE_RE.sub(" ", base)


def normalize_brand(s: str | None) -> str:
    base = normalize_token(s)
    base = _BRAND_PUNCT_RE.sub(" ", base)
    return _SPACE_RE.sub(" ", base).strip()


def normalize_category(s: str | None) -> str:
    base = normalize_token(s)
    base = _BRAND_PUNCT_RE.sub(" ", base)
    return _SPACE_RE.sub(" ", base).strip()


def normalize_packaging(s: str | None) -> str:
    token = normalize_token(s)
    return _PACKAGING_MAP.get(token, token)
