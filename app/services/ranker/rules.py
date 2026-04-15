from app.models.extraction import ExtractionResult
from app.utils.unit_converter import normalize_unit, value_to_ml


def apply_defaults(extracted: ExtractionResult) -> ExtractionResult:
    # 1. Normalize units
    extracted.unit_raw = normalize_unit(extracted.unit_raw)
    extracted.size_unit = normalize_unit(extracted.size_unit)

    # 2. Size Hint calculation
    if extracted.size_hint is None and extracted.size_value is not None and extracted.size_unit is not None:
        size_ml = value_to_ml(extracted.size_value, extracted.size_unit)
        if size_ml >= 1000:
            extracted.size_hint = "large"
        elif size_ml <= 350:
            extracted.size_hint = "small"
        else:
            extracted.size_hint = "medium"
            
    return extracted
