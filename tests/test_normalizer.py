from app.utils.normalizer import normalize_brand, normalize_category, normalize_packaging


def test_normalize_brand_cases() -> None:
    assert normalize_brand("Coca-Cola") == "coca cola"
    assert normalize_brand("COCA COLA") == "coca cola"
    assert normalize_brand("Hảo Hảo") == "hao hao"
    assert normalize_brand("TH true MILK") == "th true milk"
    assert normalize_brand(None) == ""


def test_normalize_category_cases() -> None:
    assert normalize_category("Nước Giải Khát") == "nuoc giai khat"


def test_normalize_packaging_cases() -> None:
    assert normalize_packaging("lon") == "can"
    assert normalize_packaging("ly") == "cup"
    assert normalize_packaging("THÙNG") == "case"
    assert normalize_packaging(None) == ""
