from app.models.extraction import ExtractionResult
from app.utils.unit_converter import normalize_size_unit, normalize_unit, value_to_ml


def apply_defaults(extracted: ExtractionResult) -> ExtractionResult:
    # 1. Normalize units — use dedicated functions to avoid cross-contamination
    extracted.unit_raw = normalize_unit(extracted.unit_raw)     # packaging: thùng→lon
    extracted.size_unit = normalize_size_unit(extracted.size_unit)  # volume: lít→l, ml→ml

    # 2. Size hint — tự tính nếu user đã cho size_value nhưng chưa có size_hint
    if extracted.size_hint is None and extracted.size_value is not None and extracted.size_unit is not None:
        size_ml = value_to_ml(extracted.size_value, extracted.size_unit)
        if size_ml >= 1000:
            extracted.size_hint = "large"
        elif size_ml <= 350:
            extracted.size_hint = "small"
        else:
            extracted.size_hint = "medium"
            
    return extracted
