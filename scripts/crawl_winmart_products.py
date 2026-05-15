#!/usr/bin/env python3
"""
Crawl sản phẩm từ winmart.vn, export CSV và optionally index vào Elasticsearch.

Lệnh crawl + export CSV:
    python3 -u scripts/crawl_winmart_products.py --output /tmp/winmart_products.csv --pages-per-keyword 2 --page-size 40

Lệnh crawl + index ES ngay:
    python3 -u scripts/crawl_winmart_products.py --output /tmp/winmart_products.csv --index-es

Index từ CSV có sẵn (không crawl lại):
    python3 -u scripts/crawl_winmart_products.py --from-csv /tmp/winmart_products.csv --index-es
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from typing import List, Set, Tuple

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# ──────────────────────────────────────────────
# WINMART API
# ──────────────────────────────────────────────
CATEGORY_URL = "https://api-crownx.winmart.vn/mt/api/web/v1/category"
SEARCH_URL = "https://api-crownx.winmart.vn/ss/api/v2/public/winmart/item-search"

CSV_FIELDNAMES = [
    "source_category_code", "source_category_name", "source_keyword",
    "item_no", "sku", "name", "brand", "uom",
    "mch1", "mch2", "mch3", "mch4", "mch5",
    "origin_price", "sale_price", "discount_rate", "available_quantity",
    "store_no", "seo_name", "image", "alcohol",
]


def http_json(url: str, method: str = "GET", payload: dict | None = None, timeout: int = 30) -> dict:
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "x-api-merchant": "WCM",
        "user-agent": "Mozilla/5.0 (compatible; winmart-crawler/1.0)",
    }
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = Request(url=url, data=data, headers=headers, method=method)
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def should_skip_category(name: str, code: str) -> bool:
    text = normalize_spaces(name).lower()
    if code in {"MENU51", "MENU114"}:
        return True
    blocked = ["ưu đãi hội viên", "hoi vien", "hội viên", "giá siêu rẻ", "khuyến mại", "khuyen mai"]
    return any(x in text for x in blocked)


def get_categories() -> List[dict]:
    raw = http_json(CATEGORY_URL).get("data", [])
    categories = []
    for node in raw:
        parent = (node or {}).get("parent") or {}
        p_name = normalize_spaces(parent.get("name", ""))
        p_code = parent.get("code", "")
        if not p_name or should_skip_category(p_name, p_code):
            continue
        children = []
        for child in (node.get("lstChild") or []):
            c_parent = child.get("parent") or {}
            c_name = normalize_spaces(c_parent.get("name", ""))
            c_code = c_parent.get("code", "")
            if c_name:
                children.append({"code": c_code, "name": c_name, "seo_name": c_parent.get("seoName", "")})
        categories.append({"code": p_code, "name": p_name, "seo_name": parent.get("seoName", ""), "children": children})
    return categories


def build_keywords(cat: dict) -> List[str]:
    kws = [cat["name"]]
    kws.extend(c["name"] for c in cat["children"][:3])
    seen: Set[str] = set()
    dedup = []
    for kw in kws:
        if kw.lower() not in seen:
            dedup.append(kw)
            seen.add(kw.lower())
    return dedup


def search_products(keyword: str, store_no: str, store_group_code: str, application_type: str, page: int, page_size: int) -> Tuple[List[dict], int]:
    payload = {
        "keyword": keyword, "pageNumber": page, "pageSize": page_size,
        "storeNo": store_no, "storeGroupCode": store_group_code, "applicationType": application_type,
    }
    resp = http_json(SEARCH_URL, method="POST", payload=payload)
    items = resp.get("data") or []
    total = int(((resp.get("paging") or {}).get("totalCount")) or 0)
    return items, total


def row_from_item(item: dict, source_category: dict, keyword: str) -> dict:
    price = item.get("price") or {}
    warehouse = item.get("warehouse") or {}
    return {
        "source_category_code": source_category.get("code", ""),
        "source_category_name": source_category.get("name", ""),
        "source_keyword": keyword,
        "item_no": item.get("itemNo", ""),
        "sku": item.get("sku", ""),
        "name": normalize_spaces(item.get("description") or item.get("longDescription") or ""),
        "brand": item.get("brandName", ""),
        "uom": item.get("uomName", ""),
        "mch1": item.get("mch1Name", ""),
        "mch2": item.get("mch2Name", ""),
        "mch3": item.get("mch3Name", ""),
        "mch4": item.get("mch4Name", ""),
        "mch5": item.get("mch5Name", ""),
        "origin_price": price.get("originPrice", ""),
        "sale_price": price.get("salePrice", ""),
        "discount_rate": price.get("discountRate", ""),
        "available_quantity": warehouse.get("availableQuantity", ""),
        "store_no": warehouse.get("storeNo", ""),
        "seo_name": item.get("seoName", ""),
        "image": item.get("image", ""),
        "alcohol": item.get("alcohol", False),
    }


# ──────────────────────────────────────────────
# DATA TRANSFORMATION — parse raw CSV row → ES doc
# ──────────────────────────────────────────────

# Size patterns: capture value + unit from product name
_SIZE_RE = re.compile(
    r'(\d+(?:[.,]\d+)?)\s*'
    r'(ml|ML|mL|lít|lit|l\b|L\b|kg|KG|Kg|gr?\b|GR?\b|g\b|G\b)',
    re.UNICODE,
)

_UNIT_NORM = {
    "ml": "ml", "ML": "ml", "mL": "ml",
    "lít": "l", "lit": "l", "l": "l", "L": "l",
    "kg": "kg", "KG": "kg", "Kg": "kg",
    "g": "g", "G": "g", "gr": "g", "GR": "g",
}

# Pack prefix: "Lốc 4 hộp", "Thùng 48 hộp", "Combo 3", etc.
_PACK_PREFIX_RE = re.compile(
    r'^(lốc|loc|thùng|thung|combo|bộ|bo|vỉ|vi|set)\s*(\d+)\s*\S+\s*',
    re.IGNORECASE | re.UNICODE,
)

# UOM string → (packaging_keyword, pack_count)
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
    "0.5kg": ("túi", 1), "1kg": ("túi", 1),
}

# Attribute keywords to tag from product name
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

# MCH → system category mapping (from broadest to most specific match)
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


def map_system_category(row: dict) -> str:
    text = " ".join([
        row.get("mch2", ""), row.get("mch3", ""),
        row.get("mch4", ""), row.get("mch5", ""),
        row.get("name", ""),
    ]).lower()
    for keywords, cat in _CATEGORY_RULES:
        if any(kw in text for kw in keywords):
            return cat
    return row.get("mch4", "") or row.get("mch3", "") or "Other"


def parse_size(name: str) -> tuple[float | None, str | None, float | None]:
    """Extract (size_value, size_unit, size_value_normalized) from product name."""
    matches = _SIZE_RE.findall(name)
    if not matches:
        return None, None, None
    # Take first meaningful match (skip very small numbers that are usually pack counts)
    for val_str, unit_raw in matches:
        val = float(val_str.replace(",", "."))
        unit = _UNIT_NORM.get(unit_raw, unit_raw.lower())
        if unit in ("ml", "l"):
            normalized = val * 1000 if unit == "l" else val
            if normalized >= 10:  # skip nonsense like 1ml
                return val, unit, normalized
        elif unit in ("g", "kg"):
            normalized = val * 1000 if unit == "kg" else val
            if normalized >= 10:
                return val, unit, normalized
    return None, None, None


def parse_uom(uom_raw: str) -> tuple[str, int]:
    """Parse UOM string → (packaging, pack_count). E.g. 'Gói 4' → ('gói', 4)."""
    s = normalize_spaces(uom_raw).lower()
    # Handle "Gói 4", "Gói 3", etc.
    m = re.match(r'^(\S+)\s+(\d+)$', s)
    if m:
        base, count = m.group(1), int(m.group(2))
        pkg, _ = _UOM_MAP.get(base, (base, 1))
        return pkg, count
    pkg, cnt = _UOM_MAP.get(s, (s, 1))
    return pkg, cnt


def extract_base_name(name: str) -> str:
    """Strip pack prefix ('Lốc 4 hộp', 'Thùng 48 hộp') from name."""
    cleaned = _PACK_PREFIX_RE.sub("", name).strip()
    return cleaned if cleaned else name


def extract_tags(name: str, mch4: str, mch5: str) -> list[str]:
    """Extract attribute tags from product name and category."""
    name_lower = name.lower()
    tags = []
    for keyword, tag in _ATTR_TAGS:
        if keyword in name_lower:
            tags.append(tag)
    # Add subcategory as tag if meaningful
    for extra in [mch4, mch5]:
        if extra and len(extra) < 40 and extra not in ("", "Other"):
            tags.append(extra.lower())
    return list(dict.fromkeys(tags))  # dedup, preserve order


def is_best_seller_proxy(row: dict) -> bool:
    try:
        qty = int(row.get("available_quantity") or 0)
        discount = float(row.get("discount_rate") or 0)
        return qty > 30 and discount > 0
    except (ValueError, TypeError):
        return False


def build_embed_text(base_name: str, brand: str, category: str, mch3: str, mch4: str, mch5: str, tags: list[str]) -> str:
    """
    Compose rich embedding text combining product identity + brand + category context + attributes.
    Goal: vector should capture WHAT the product is, WHO makes it, WHAT KIND it is.
    """
    parts = [
        base_name,
        brand,
        category,
        mch3, mch4, mch5,
        " ".join(tags),
    ]
    return " ".join(p for p in parts if p and p.strip())


def transform_row(row: dict) -> dict:
    """Transform a raw CSV row into an ES document."""
    name = row.get("name", "")
    brand = normalize_spaces(row.get("brand", ""))
    uom_raw = row.get("uom", "")

    size_value, size_unit, size_normalized = parse_size(name)
    packaging, pack_count = parse_uom(uom_raw)
    base_name = extract_base_name(name)
    category = map_system_category(row)
    tags = extract_tags(name, row.get("mch4", ""), row.get("mch5", ""))
    embed_text = build_embed_text(
        base_name=base_name,
        brand=brand,
        category=category,
        mch3=row.get("mch3", ""),
        mch4=row.get("mch4", ""),
        mch5=row.get("mch5", ""),
        tags=tags,
    )

    try:
        sale_price = float(row.get("sale_price") or 0)
    except (ValueError, TypeError):
        sale_price = 0.0

    return {
        "id": row.get("sku", ""),
        "item_no": row.get("item_no", ""),
        "name": name,
        "base_name": base_name,
        "brand": brand.lower(),
        "brand_display": brand,
        "category": category,
        "mch_path": " > ".join(filter(None, [
            row.get("mch1", ""), row.get("mch2", ""),
            row.get("mch3", ""), row.get("mch4", ""), row.get("mch5", ""),
        ])),
        "size_value": size_value,
        "size_unit": size_unit,
        "size_value_ml": size_normalized,
        "packaging": packaging,
        "pack_count": pack_count,
        "uom_raw": uom_raw,
        "tags": [t for t in tags if t],
        "is_best_seller": is_best_seller_proxy(row),
        "sale_price": sale_price,
        "image": row.get("image", ""),
        "seo_name": row.get("seo_name", ""),
        "embed_text": embed_text,
    }


# ──────────────────────────────────────────────
# ELASTICSEARCH INDEXING
# ──────────────────────────────────────────────

def build_index_mapping(vector_dims: int) -> dict:
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
                # ── Identity ──
                "id":           {"type": "keyword"},
                "item_no":      {"type": "keyword"},
                "seo_name":     {"type": "keyword"},
                # ── Search text fields ──
                "name":         {"type": "text", "analyzer": "vn_text"},
                "base_name":    {"type": "text", "analyzer": "vn_text", "boost": 2},
                "brand":        {"type": "keyword"},          # exact filter
                "brand_display":{"type": "text", "analyzer": "vn_text"},  # fuzzy search
                # ── Category ──
                "category":     {"type": "keyword"},
                "mch_path":     {"type": "text", "analyzer": "vn_text"},
                # ── Size ──
                "size_value":   {"type": "float"},
                "size_unit":    {"type": "keyword"},
                "size_value_ml":{"type": "float"},            # filterable numeric
                # ── Packaging ──
                "packaging":    {"type": "keyword"},
                "pack_count":   {"type": "integer"},
                "uom_raw":      {"type": "keyword"},
                # ── Attributes ──
                "tags":         {"type": "keyword"},          # exact match for must_not/should
                # ── Commerce ──
                "is_best_seller":{"type": "boolean"},
                "sale_price":   {"type": "float"},
                "image":        {"type": "keyword", "index": False},
                # ── Vector ──
                "name_vector":  {
                    "type": "dense_vector",
                    "dims": vector_dims,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
    }


def index_documents(docs: list[dict], gemini_client, es_client, index_name: str, batch_size: int = 50) -> None:
    from elasticsearch.helpers import bulk

    print(f"Getting vector dims from Gemini...", flush=True)
    sample_vec = gemini_client.embed_text(docs[0]["embed_text"])
    vector_dims = len(sample_vec)
    print(f"Vector dims: {vector_dims}", flush=True)

    if es_client.indices.exists(index=index_name):
        es_client.indices.delete(index=index_name)
        print(f"Deleted existing index '{index_name}'", flush=True)

    es_client.indices.create(index=index_name, body=build_index_mapping(vector_dims))
    print(f"Created index '{index_name}' with new mapping", flush=True)

    total = len(docs)
    actions = []
    embedded = 0

    for i, doc in enumerate(docs):
        vector = gemini_client.embed_text(doc["embed_text"])
        source = {k: v for k, v in doc.items() if k != "embed_text"}
        source["name_vector"] = vector
        actions.append({"_index": index_name, "_id": doc["id"], "_source": source})
        embedded += 1

        if len(actions) >= batch_size or i == total - 1:
            bulk(es_client, actions)
            es_client.indices.refresh(index=index_name)
            print(f"  Indexed {embedded}/{total}", flush=True)
            actions = []

    print(f"Done. {embedded} documents indexed into '{index_name}'", flush=True)


# ──────────────────────────────────────────────
# CRAWL
# ──────────────────────────────────────────────

def crawl_to_csv(
    output_csv: str,
    store_no: str,
    store_group_code: str,
    application_type: str,
    pages_per_keyword: int,
    page_size: int,
    sleep_ms: int,
    max_categories: int,
) -> list[dict]:
    categories = get_categories()
    if max_categories > 0:
        categories = categories[:max_categories]

    rows: list[dict] = []
    seen_item_uom: Set[Tuple[str, str]] = set()

    for idx, cat in enumerate(categories, start=1):
        keywords = build_keywords(cat)
        print(f"[{idx}/{len(categories)}] {cat['name']} | keywords={len(keywords)}", flush=True)
        for kw in keywords:
            for page in range(1, pages_per_keyword + 1):
                try:
                    items, total = search_products(
                        keyword=kw,
                        store_no=store_no,
                        store_group_code=store_group_code,
                        application_type=application_type,
                        page=page,
                        page_size=page_size,
                    )
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
                    print(f"  - WARN keyword='{kw}' page={page}: {e}", flush=True)
                    break

                if page == 1:
                    print(f"  - keyword='{kw}' total={total}", flush=True)
                if not items:
                    break

                for item in items:
                    key = (str(item.get("itemNo", "")), str(item.get("uomId", "")))
                    if key in seen_item_uom:
                        continue
                    seen_item_uom.add(key)
                    rows.append(row_from_item(item, cat, kw))

                if sleep_ms > 0:
                    time.sleep(sleep_ms / 1000)

    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Crawl done. {len(rows)} rows → {output_csv}", flush=True)
    return rows


def load_csv(csv_path: str) -> list[dict]:
    with open(csv_path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ──────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl WinMart products → CSV (+ optional ES indexing)")
    p.add_argument("--output", default="/tmp/winmart_products.csv", help="Output CSV path")
    p.add_argument("--from-csv", default="", help="Skip crawl, index from existing CSV file")
    p.add_argument("--index-es", action="store_true", help="Index into Elasticsearch after crawl")
    p.add_argument("--store-no", default="1535")
    p.add_argument("--store-group-code", default="1999")
    p.add_argument("--application-type", default="WINMART")
    p.add_argument("--pages-per-keyword", type=int, default=2)
    p.add_argument("--page-size", type=int, default=40)
    p.add_argument("--sleep-ms", type=int, default=120)
    p.add_argument("--max-categories", type=int, default=0, help="0 = all")
    p.add_argument("--embed-batch", type=int, default=50, help="ES bulk batch size")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.from_csv:
        print(f"Loading from CSV: {args.from_csv}", flush=True)
        raw_rows = load_csv(args.from_csv)
    else:
        raw_rows = crawl_to_csv(
            output_csv=args.output,
            store_no=args.store_no,
            store_group_code=args.store_group_code,
            application_type=args.application_type,
            pages_per_keyword=args.pages_per_keyword,
            page_size=args.page_size,
            sleep_ms=args.sleep_ms,
            max_categories=args.max_categories,
        )

    if not args.index_es:
        print("--index-es not set, skipping ES indexing.", flush=True)
        return

    print(f"\nTransforming {len(raw_rows)} rows...", flush=True)
    docs = [transform_row(r) for r in raw_rows if r.get("name")]
    # Filter out rows with no meaningful data
    docs = [d for d in docs if d["id"] and d["name"]]
    print(f"{len(docs)} valid documents after transform", flush=True)

    from app.core.clients.elastic import get_client
    from app.core.clients.gemini import GeminiClient
    from app.core.config import settings

    gemini = GeminiClient()
    es = get_client()

    index_documents(
        docs=docs,
        gemini_client=gemini,
        es_client=es,
        index_name=settings.elastic_index,
        batch_size=args.embed_batch,
    )


if __name__ == "__main__":
    main()
