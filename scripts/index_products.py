#!/usr/bin/env python3
"""
Đọc CSV sản phẩm → transform → embed (Gemini) → index vào Elasticsearch.

Usage:
    python3 -u scripts/index_products.py --csv data/winmart_products.csv
    python3 -u scripts/index_products.py --csv data/winmart_products.csv --batch-size 100
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from elasticsearch.helpers import bulk

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.clients.elastic import get_client
from app.core.clients.gemini import GeminiClient
from app.core.config import settings
from app.utils.normalizer import normalize_brand, normalize_category


# ──────────────────────────────────────────────
# REGEX / LOOKUP TABLES
# ──────────────────────────────────────────────

_SIZE_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*(ml|ML|mL|lít|lit|l\b|L\b|kg|KG|Kg|gr?\b|GR?\b|g\b|G\b)',
    re.UNICODE,
)
_UNIT_NORM = {
    "ml": "ml", "ML": "ml", "mL": "ml",
    "lít": "l", "lit": "l", "l": "l", "L": "l",
    "kg": "kg", "KG": "kg", "Kg": "kg",
    "g": "g", "G": "g", "gr": "g", "GR": "g",
}
_PACK_PREFIX_RE = re.compile(
    r'^(lốc|loc|thùng|thung|combo|bộ|bo|vỉ|vi|set)\s*(\d+)\s*\S+\s*',
    re.IGNORECASE | re.UNICODE,
)
_UOM_MAP: dict[str, tuple[str, int]] = {
    "lon": ("lon", 1), "can": ("lon", 1),
    "chai": ("chai", 1),
    "hộp": ("hộp", 1), "hop": ("hộp", 1),
    "gói": ("gói", 1), "goi": ("gói", 1),
    "túi": ("túi", 1), "tui": ("túi", 1),
    "ly": ("ly", 1),
    "cái": ("cái", 1), "cai": ("cái", 1), "qủa": ("quả", 1),
    "thùng": ("thùng", 24), "thung": ("thùng", 24),
    "lốc": ("lốc", 6), "loc": ("lốc", 6),
    "vỉ": ("vỉ", 1), "vi": ("vỉ", 1),
}
_ATTR_TAGS = [
    ("ít đường", "ít đường"), ("it duong", "ít đường"),
    ("không đường", "không đường"), ("ko đường", "không đường"),
    ("có đường", "có đường"),
    ("nguyên chất", "nguyên chất"),
    ("ít béo", "ít béo"), ("tách béo", "tách béo"),
    ("hương socola", "socola"), ("hương dâu", "dâu"),
    ("hương cam", "cam"), ("hương chanh", "chanh"),
    ("zero", "zero"), ("diet", "diet"),
    ("hữu cơ", "hữu cơ"), ("organic", "hữu cơ"),
    ("tiệt trùng", "tiệt trùng"),
    ("lên men", "lên men"),
    ("tăng lực", "tăng lực"),
]
_CATEGORY_RULES: list[tuple[list[str], str]] = [
    (["bia", "beer"], "Beer"),
    (["nước ngọt", "nước có ga", "soft drink", "nước giải khát có ga"], "Soft Drink"),
    (["nước uống", "nước khoáng", "nước suối", "nước tinh khiết"], "Water"),
    (["sữa tươi", "sữa tiệt trùng"], "Milk"),
    (["sữa chua"], "Yogurt"),
    (["sữa hạt", "sữa đậu", "sữa nguồn gốc thực vật"], "Plant Milk"),
    (["sữa bột", "sữa đặc", "dinh dưỡng trẻ em", "sữa công thức"], "Formula Milk"),
    (["phô mai", "bơ, sữa, trứng", "váng sữa"], "Dairy"),
    (["tăng lực", "energy"], "Energy Drink"),
    (["nước trái cây", "nước ép", "sinh tố", "nước uống đóng chai"], "Juice"),
    (["trà", "tea", "coffee", "cà phê"], "Coffee & Tea"),
    (["snack", "bánh kẹo", "khoai tây chiên", "bim bim"], "Snack"),
    (["bánh", "bánh ngọt", "bánh quy", "bánh mì"], "Bakery"),
    (["kẹo", "chocolate"], "Candy"),
    (["mì", "bún", "phở", "cháo ăn liền", "instant noodle"], "Instant Noodle"),
    (["gạo", "rice"], "Rice"),
    (["dầu ăn", "gia vị", "nước mắm", "tương", "sauce", "muối", "đường"], "Condiment"),
    (["thực phẩm chế biến", "thực phẩm đông lạnh"], "Processed Food"),
    (["rau", "củ", "quả", "trái cây", "rau gia vị"], "Fresh Produce"),
    (["giặt", "tẩy", "lau", "vệ sinh nhà", "nước rửa"], "Cleaning"),
    (["sữa tắm", "dầu gội", "chăm sóc da", "chăm sóc tóc", "mỹ phẩm", "son môi"], "Personal Care"),
    (["đồ dùng nhà bếp", "gia dụng", "đồ dùng"], "Household"),
]


# ──────────────────────────────────────────────
# TRANSFORM
# ──────────────────────────────────────────────

def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _map_category(row: dict) -> str:
    text = " ".join([row.get("mch2",""), row.get("mch3",""), row.get("mch4",""), row.get("mch5",""), row.get("name","")]).lower()
    for keywords, cat in _CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return cat
    return row.get("mch4","") or row.get("mch3","") or "Other"


def _parse_size(name: str) -> tuple[float | None, str | None, float | None]:
    for val_str, unit_raw in _SIZE_RE.findall(name):
        val  = float(val_str.replace(",", "."))
        unit = _UNIT_NORM.get(unit_raw, unit_raw.lower())
        if unit in ("ml", "l"):
            norm = val * 1000 if unit == "l" else val
            if norm >= 10:
                return val, unit, norm
        elif unit in ("g", "kg"):
            norm = val * 1000 if unit == "kg" else val
            if norm >= 10:
                return val, unit, norm
    return None, None, None


def _parse_uom(uom_raw: str) -> tuple[str, int]:
    s = _normalize_spaces(uom_raw).lower()
    m = re.match(r'^(\S+)\s+(\d+)$', s)
    if m:
        pkg, _ = _UOM_MAP.get(m.group(1), (m.group(1), 1))
        return pkg, int(m.group(2))
    return _UOM_MAP.get(s, (s, 1))


def _extract_base_name(name: str) -> str:
    cleaned = _PACK_PREFIX_RE.sub("", name).strip()
    return cleaned if cleaned else name


def _extract_tags(name: str, mch4: str, mch5: str) -> list[str]:
    name_lower = name.lower()
    tags = [tag for kw, tag in _ATTR_TAGS if kw in name_lower]
    for extra in [mch4, mch5]:
        if extra and len(extra) < 40:
            tags.append(extra.lower())
    return list(dict.fromkeys(tags))


def _is_best_seller(row: dict) -> bool:
    try:
        return int(row.get("available_quantity") or 0) > 30 and float(row.get("discount_rate") or 0) > 0
    except (ValueError, TypeError):
        return False


def transform(row: dict) -> dict:
    name      = row.get("name", "")
    brand     = _normalize_spaces(row.get("brand", ""))
    uom_raw   = row.get("uom", "")
    base_name = _extract_base_name(name)
    category  = _map_category(row)
    tags      = _extract_tags(name, row.get("mch4",""), row.get("mch5",""))
    sv, su, snorm = _parse_size(name)
    packaging, pack_count = _parse_uom(uom_raw)

    embed_text = " ".join(p for p in [
        base_name, brand, category,
        row.get("mch3",""), row.get("mch4",""), row.get("mch5",""),
        " ".join(tags),
    ] if p and p.strip())

    return {
        "id":            row.get("sku", ""),
        "item_no":       row.get("item_no", ""),
        "name":          name,
        "base_name":     base_name,
        "brand":         brand.lower(),
        "brand_norm":    normalize_brand(brand),
        "brand_display": brand,
        "category":      category,
        "category_norm": normalize_category(category),
        "mch_path":      " > ".join(filter(None, [row.get(f"mch{i}","") for i in range(1,6)])),
        "size_value":    sv,
        "size_unit":     su,
        "size_value_ml": snorm,
        "packaging":     packaging,
        "pack_count":    pack_count,
        "uom_raw":       uom_raw,
        "tags":          [t for t in tags if t],
        "is_best_seller":_is_best_seller(row),
        "seo_name":      row.get("seo_name", ""),
        "embed_text":    embed_text,
    }


# ──────────────────────────────────────────────
# ES MAPPING
# ──────────────────────────────────────────────

def build_mapping(vector_dims: int) -> dict:
    return {
        "settings": {
            "analysis": {
                "analyzer": {
                    "vn_text": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding"],
                    }
                }
            }
        },
        "mappings": {
            "properties": {
                "id":            {"type": "keyword"},
                "item_no":       {"type": "keyword"},
                "seo_name":      {"type": "keyword"},
                "name":          {"type": "text", "analyzer": "vn_text"},
                "base_name":     {"type": "text", "analyzer": "vn_text"},
                "brand":         {"type": "keyword"},
                "brand_norm":    {"type": "keyword"},
                "brand_display": {"type": "text", "analyzer": "vn_text"},
                "category":      {"type": "keyword"},
                "category_norm": {"type": "keyword"},
                "mch_path":      {"type": "text", "analyzer": "vn_text"},
                "size_value":    {"type": "float"},
                "size_unit":     {"type": "keyword"},
                "size_value_ml": {"type": "float"},
                "packaging":     {"type": "keyword"},
                "pack_count":    {"type": "integer"},
                "uom_raw":       {"type": "keyword"},
                "tags":          {"type": "keyword"},
                "is_best_seller":{"type": "boolean"},
                "name_vector": {
                    "type": "dense_vector",
                    "dims": vector_dims,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    }


# ──────────────────────────────────────────────
# INDEX
# ──────────────────────────────────────────────

def index(csv_path: str, batch_size: int, reset: bool, offset: int, limit: int | None) -> None:
    with open(csv_path, newline="", encoding="utf-8") as f:
        raw_rows = list(csv.DictReader(f))

    all_docs = [transform(r) for r in raw_rows if r.get("name")]
    all_docs = [d for d in all_docs if d["id"] and d["name"]]
    total_csv = len(all_docs)
    print(f"{total_csv} valid documents from {csv_path}", flush=True)

    # Slice the window to process
    end = offset + limit if limit else total_csv
    docs = all_docs[offset:end]
    print(f"Processing offset={offset} limit={limit or 'all'} → {len(docs)} docs (total in CSV: {total_csv})", flush=True)

    if not docs:
        print("Nothing to index in this range.", flush=True)
        return

    gemini = GeminiClient()
    es     = get_client()

    # Create / reset index only on the first page (offset == 0)
    if offset == 0:
        sample_vec  = gemini.embed_text(docs[0]["embed_text"])
        vector_dims = len(sample_vec)
        print(f"Vector dims: {vector_dims}", flush=True)

        if es.indices.exists(index=settings.elastic_index) and reset:
            es.indices.delete(index=settings.elastic_index)
            print(f"Deleted existing index '{settings.elastic_index}'", flush=True)
        elif es.indices.exists(index=settings.elastic_index) and not reset:
            raise RuntimeError(
                f"Index '{settings.elastic_index}' already exists. Pass --reset to recreate it."
            )

        es.indices.create(index=settings.elastic_index, body=build_mapping(vector_dims))
        print(f"Created index '{settings.elastic_index}'", flush=True)
    else:
        # Continuing — index must already exist
        if not es.indices.exists(index=settings.elastic_index):
            raise RuntimeError(
                f"Index '{settings.elastic_index}' not found. Run with offset=0 --reset first."
            )
        print(f"Continuing into existing index '{settings.elastic_index}'", flush=True)

    actions = []
    done    = 0

    for i, doc in enumerate(docs):
        vec    = gemini.embed_text(doc["embed_text"])
        source = {k: v for k, v in doc.items() if k != "embed_text"}
        source["name_vector"] = vec
        actions.append({"_index": settings.elastic_index, "_id": doc["id"], "_source": source})
        done += 1

        if len(actions) >= batch_size or i == len(docs) - 1:
            bulk(es, actions)
            es.indices.refresh(index=settings.elastic_index)
            print(f"  {offset + done}/{total_csv} indexed", flush=True)
            actions = []

    print(f"Done. {done} docs indexed (offset {offset}→{offset+done} of {total_csv}).", flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="CSV → transform → embed → Elasticsearch")
    p.add_argument("--csv",        default="data/winmart_products.csv")
    p.add_argument("--batch-size", type=int, default=50)
    p.add_argument("--reset",  action="store_true", help="Delete and recreate index (only used with --offset 0)")
    p.add_argument("--offset", type=int, default=0,    help="Skip first N documents")
    p.add_argument("--limit",  type=int, default=None, help="Max documents to index in this run")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    index(
        csv_path=args.csv,
        batch_size=args.batch_size,
        reset=args.reset,
        offset=args.offset,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
