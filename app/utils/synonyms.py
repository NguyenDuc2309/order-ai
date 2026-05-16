from app.utils.normalizer import normalize_brand


BRAND_ALIAS_MAP = {
    "bo huc": "red bull",
    "bò húc": "red bull",
    "coke": "coca cola",
    "coca": "coca cola",
}


def resolve_brand_alias(brand: str | None) -> str | None:
    if not brand:
        return brand
    key = normalize_brand(brand)
    return BRAND_ALIAS_MAP.get(key, brand)
