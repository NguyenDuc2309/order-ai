PACK_CONVERSIONS = {
    "thùng": {"unit": "lon", "count": 24},
    "két": {"unit": "chai", "count": 24},
    "lốc": {"unit": "lon", "count": 6},
}


def value_to_ml(value: float, unit: str | None) -> float:
    if not value:
        return 0.0
    if unit and unit.lower() == "l":
        return value * 1000
    return value


def normalize_unit(unit_raw: str | None) -> str | None:
    """Normalize packaging/container units (thùng, lốc, lon, chai…)."""
    if not unit_raw:
        return None
    unit = unit_raw.strip().lower()
    if unit in PACK_CONVERSIONS:
        return PACK_CONVERSIONS[unit]["unit"]
    return unit


def normalize_size_unit(size_unit: str | None) -> str | None:
    """Normalize volume units only (l, ml). Never maps packaging terms."""
    if not size_unit:
        return None
    u = size_unit.strip().lower()
    if u in {"lít", "lit", "l", "liter", "litre"}:
        return "l"
    if u in {"ml", "mililit", "milliliter", "mililít"}:
        return "ml"
    return u


def pack_count(unit_raw: str | None) -> int:
    if not unit_raw:
        return 1
    unit = unit_raw.strip().lower()
    return PACK_CONVERSIONS.get(unit, {}).get("count", 1)
