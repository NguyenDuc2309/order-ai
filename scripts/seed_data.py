from __future__ import annotations

import sys
from pathlib import Path
import uuid
import random
import unicodedata
import re

from elasticsearch.helpers import bulk

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.clients.elastic import get_client
from app.core.clients.gemini import GeminiClient
from app.core.config import settings


# =========================
# CONFIG
# =========================
MAX_ITEMS = 200

EXTRA_TAGS = ["", "khuyến mãi", "ít đường", "cao cấp"]
PACK_OPTIONS = [None, ("lốc", 6), ("thùng", 24)]
CATEGORY_DISPLAY = {
    "soft drink": "Soft Drink",
    "water": "Water",
    "beer": "Beer",
    "milk": "Milk",
    "energy drink": "Energy Drink",
    "snack": "Snack",
    "instant noodle": "Instant Noodle",
    "rice": "Rice",
    "sauce": "Sauce",
    "cleaning": "Cleaning",
}


# =========================
# BASE PRODUCTS (REAL POS STYLE)
# =========================
BASE_PRODUCTS = [
    ("Coca Cola", "coca cola", "soft drink", [330, 390, 1500], ["lon", "chai"]),
    ("Pepsi", "pepsi", "soft drink", [330, 390, 1500], ["lon", "chai"]),
    ("Sprite", "sprite", "soft drink", [330, 390, 1500], ["lon", "chai"]),

    ("Lavie", "lavie", "water", [350, 500, 1500], ["chai"]),
    ("Aquafina", "aquafina", "water", [350, 500, 1500], ["chai"]),

    ("Tiger", "tiger", "beer", [330], ["lon", "chai"]),
    ("Heineken", "heineken", "beer", [330], ["lon", "chai"]),
    ("Bia Sài Gòn", "bia sai gon", "beer", [330], ["lon", "chai"]),

    ("Vinamilk", "vinamilk", "milk", [180, 1000], ["hộp"]),
    ("TH True Milk", "th true milk", "milk", [180, 1000], ["hộp"]),

    ("Red Bull", "red bull", "energy drink", [250], ["lon"]),
    ("Sting", "sting", "energy drink", [330], ["lon", "chai"]),

    ("Snack Oishi", "oishi", "snack", [40, 60], ["gói"]),
    ("Khoai Tây Poca", "poca", "snack", [35, 60], ["gói"]),

    ("Mì Hảo Hảo", "hao hao", "instant noodle", [75], ["gói", "ly"]),
    ("Mì Omachi", "omachi", "instant noodle", [80], ["gói", "ly"]),

    ("Gạo ST25", "gao st25", "rice", [5000], ["túi"]),
    ("Gạo Jasmine", "gao jasmine", "rice", [5000], ["túi"]),

    ("Nước mắm Nam Ngư", "nam ngu", "sauce", [500], ["chai"]),
    ("Tương ớt Chinsu", "chinsu", "sauce", [250], ["chai"]),

    ("Nước rửa chén Sunlight", "sunlight", "cleaning", [750], ["chai"]),
    ("Bột giặt Omo", "omo", "cleaning", [3000], ["túi"]),
]


# =========================
# NORMALIZE (SEARCH ONLY)
# =========================
def normalize_text(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = re.sub(r"[^a-z0-9\s]", "", text)
    return text


# =========================
# MAPPING
# =========================
def build_index_mapping(vector_dims: int):
    return {
        "mappings": {
            "properties": {
                "id": {"type": "keyword"},
                "name": {"type": "text"},           # hiển thị
                "base_name": {"type": "text"},
                "brand_display": {"type": "text"},
                "mch_path": {"type": "text"},
                "search_text": {"type": "text"},    # search
                "brand": {"type": "keyword"},
                "category": {"type": "keyword"},
                "size_value": {"type": "float"},
                "size_unit": {"type": "keyword"},
                "size_value_ml": {"type": "float"},
                "packaging": {"type": "keyword"},
                "pack_count": {"type": "integer"},
                "tags": {"type": "keyword"},
                "is_best_seller": {"type": "boolean"},
                "name_vector": {
                    "type": "dense_vector",
                    "dims": vector_dims,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        }
    }


# =========================
# GENERATOR
# =========================
def build_products():
    products = []

    for base_name, brand, category, sizes, packagings in BASE_PRODUCTS:
        category_display = CATEGORY_DISPLAY.get(category, category.title())
        brand_display = base_name.title()
        for size in sizes:
            for packaging in packagings:
                for tag in EXTRA_TAGS:
                    for pack in PACK_OPTIONS:

                        if len(products) >= MAX_ITEMS:
                            return products

                        # tránh combo vô lý
                        if pack and size > 1000:
                            continue

                        name = f"{base_name} {packaging} {size}ml"

                        if pack:
                            name += f" {pack[0]} {pack[1]}"

                        if tag:
                            name += f" {tag}"

                        search_text = normalize_text(name)
                        tags = [value for value in [brand, category_display, packaging, tag] if value]

                        product = {
                            "id": str(uuid.uuid4()),
                            "name": name,  # ✅ giữ nguyên tiếng Việt
                            "base_name": base_name,
                            "brand_display": brand_display,
                            "mch_path": category_display,
                            "search_text": search_text,
                            "brand": brand,
                            "category": category_display,
                            "size_value": float(size),
                            "size_unit": "ml",
                            "size_value_ml": float(size),
                            "packaging": packaging,
                            "pack_count": pack[1] if pack else 1,
                            "tags": tags,
                            "is_best_seller": False,
                            "embed_text": f"{name} {brand_display} {category_display}",
                        }

                        products.append(product)

    return products


# =========================
# MAIN
# =========================
def main():
    client = get_client()
    gemini = GeminiClient()

    print("🔄 Generating products...")
    products = build_products()
    print(f"✅ Generated {len(products)} products")

    print("🔄 Getting embedding dimension...")
    dummy_vector = gemini.embed_text("coca")
    vector_dims = len(dummy_vector)

    if client.indices.exists(index=settings.elastic_index):
        client.indices.delete(index=settings.elastic_index)

    client.indices.create(
        index=settings.elastic_index,
        body=build_index_mapping(vector_dims)
    )

    print("🔄 Embedding + indexing...")

    actions = []
    for item in products:
        vector = gemini.embed_text(item["embed_text"])
        source = {key: value for key, value in item.items() if key != "embed_text"}

        actions.append({
            "_index": settings.elastic_index,
            "_id": item["id"],
            "_source": {**source, "name_vector": vector}
        })

    bulk(client, actions)
    client.indices.refresh(index=settings.elastic_index)

    print(f"🚀 DONE: {len(products)} products indexed")


if __name__ == "__main__":
    main()
