#!/usr/bin/env python3
import argparse
import csv
import json
import re
import time
from typing import Dict, Iterable, List, Set, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

CATEGORY_URL = "https://api-crownx.winmart.vn/mt/api/web/v1/category"
SEARCH_URL = "https://api-crownx.winmart.vn/ss/api/v2/public/winmart/item-search"


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
        categories.append(
            {
                "code": p_code,
                "name": p_name,
                "seo_name": parent.get("seoName", ""),
                "children": children,
            }
        )
    return categories


def build_keywords(cat: dict) -> List[str]:
    kws = [cat["name"]]
    kws.extend(c["name"] for c in cat["children"][:3])
    dedup = []
    seen = set()
    for kw in kws:
        key = kw.lower()
        if key not in seen:
            dedup.append(kw)
            seen.add(key)
    return dedup


def search_products(keyword: str, store_no: str, store_group_code: str, application_type: str, page: int, page_size: int) -> Tuple[List[dict], int]:
    payload = {
        "keyword": keyword,
        "pageNumber": page,
        "pageSize": page_size,
        "storeNo": store_no,
        "storeGroupCode": store_group_code,
        "applicationType": application_type,
    }
    resp = http_json(SEARCH_URL, method="POST", payload=payload)
    items = resp.get("data") or []
    total = ((resp.get("paging") or {}).get("totalCount")) or 0
    return items, int(total)


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


def crawl(
    output_csv: str,
    store_no: str,
    store_group_code: str,
    application_type: str,
    pages_per_keyword: int,
    page_size: int,
    sleep_ms: int,
    max_categories: int,
) -> None:
    categories = get_categories()
    if max_categories > 0:
        categories = categories[:max_categories]
    rows: List[dict] = []
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

    fieldnames = [
        "source_category_code",
        "source_category_name",
        "source_keyword",
        "item_no",
        "sku",
        "name",
        "brand",
        "uom",
        "mch1",
        "mch2",
        "mch3",
        "mch4",
        "mch5",
        "origin_price",
        "sale_price",
        "discount_rate",
        "available_quantity",
        "store_no",
        "seo_name",
        "image",
        "alcohol",
    ]
    with open(output_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Done. Wrote {len(rows)} rows -> {output_csv}", flush=True)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Crawl diversified product pool from winmart.vn and export CSV")
    p.add_argument("--output", default="reports/winmart_products.csv", help="Output CSV path")
    p.add_argument("--store-no", default="1535", help="WinMart storeNo")
    p.add_argument("--store-group-code", default="1999", help="Store group code")
    p.add_argument("--application-type", default="WINMART", help="Application type for item-search API")
    p.add_argument("--pages-per-keyword", type=int, default=2, help="How many pages to fetch per keyword")
    p.add_argument("--page-size", type=int, default=40, help="Page size per request")
    p.add_argument("--sleep-ms", type=int, default=120, help="Sleep between requests (ms)")
    p.add_argument("--max-categories", type=int, default=0, help="Limit number of categories for quick test (0 = all)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    crawl(
        output_csv=args.output,
        store_no=args.store_no,
        store_group_code=args.store_group_code,
        application_type=args.application_type,
        pages_per_keyword=args.pages_per_keyword,
        page_size=args.page_size,
        sleep_ms=args.sleep_ms,
        max_categories=args.max_categories,
    )


if __name__ == "__main__":
    main()
