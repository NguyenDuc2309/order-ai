PACK_CONVERSIONS = {
    "thùng": {"unit": "lon", "count": 24},
    "thung": {"unit": "lon", "count": 24},
    "két": {"unit": "chai", "count": 24},
    "ket": {"unit": "lon", "count": 24},
    "lốc": {"unit": "lon", "count": 6},
    "loc": {"unit": "lon", "count": 6},
}


def value_to_ml(value: float, unit: str | None) -> float:
    if not value:
        return 0.0
    if unit and unit.lower() == "l":
        return value * 1000
    return value


def normalize_unit(unit_raw: str | None) -> str | None:
    if not unit_raw:
        return None
    unit = unit_raw.strip().lower()
    
    # 1. Pack conversions
    if unit in PACK_CONVERSIONS:
        return PACK_CONVERSIONS[unit]["unit"]
        
    # 2. Basic unit normalization
    if unit in {"lít", "lit", "l"}:
        return "l"
    if unit in {"mililit", "ml"}:
        return "ml"
        
    return unit


def pack_count(unit_raw: str | None) -> int:
    if not unit_raw:
        return 1
    unit = unit_raw.strip().lower()
    return PACK_CONVERSIONS.get(unit, {}).get("count", 1)
