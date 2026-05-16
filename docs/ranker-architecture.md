# Ranker Architecture

## Overview

Order-AI sử dụng **Constraint Audit + AND Gate** pattern để quyết định kết quả tìm kiếm. Pipeline gồm 4 bước chính sau ES hybrid search.

```
Query (text)
  │
  ▼
[extract_node]                          app/graph/nodes.py
  ├─ Gemini LLM → ExtractionResult      brand, category, qty, size, is_exact_request, must_not
  ├─ Gemini embed → query_vector
  └─ Post-normalize: normalize_brand(resolve_brand_alias(extraction.brand))
  │
  ▼
[build_query_node]                      app/services/search/query_builder.py
  ├─ BM25 multi-match (base_name^4, name^3, brand_display^3, mch_path^2, tags)
  ├─ kNN cosine (name_vector, k=20, num_candidates=200)
  └─ Soft boost: brand_norm^60 + category_norm^30 + packaging^20
     (NO hard size filter — StructuralScorer handles size post-retrieval)
  │
  ▼
[search_node]                           app/services/search/es_service.py
  └─ ES hybrid search → top-20 rows
  │
  ▼
[decide_node]                           app/graph/nodes.py
  │
  ├─ StructuralScorer.score(rows, extraction)
  │     For each product:
  │       audit = ConstraintAuditor.audit(extraction, product)
  │       score = raw_es_score + brand_w + category_w + size_w + packaging_w + attr_w
  │       → ScoredRow(product, raw_es_score, structural_score, audit)
  │
  └─ Decider.decide(scored_rows, extraction)
        │
        ├─ Gate 1: no_result
        │   (score < MIN_RELEVANCE AND satisfied=0 AND specified≥1)
        │
        ├─ Gate 2: exact_match (AND gate)
        │   hard_pass AND gap > threshold AND audit_fraction ≥ 0.8
        │
        └─ Gate 3: needs_clarification (default)
              top_3_diverse: best_seller + largest_size + smallest_size
  │
  ▼
SearchResponse { status, type, confidence, items[], message }
```

---

## Các module chính

### `app/utils/normalizer.py`

Chuẩn hoá text cho index-time và query-time matching.

| Function | Mô tả |
|---|---|
| `normalize_token(s)` | lowercase + strip diacritics (NFD/Mn) + collapse whitespace |
| `normalize_brand(s)` | normalize_token + strip punctuation (`-_./ → space`) |
| `normalize_category(s)` | Như normalize_brand |
| `normalize_packaging(s)` | Map về canonical form: lon→can, chai→bottle, thùng→case, hộp→box, gói→pack, ly→cup |

**Quy tắc:** Hàm normalize phải **thuần túy** (pure function), không side-effect, không IO.

---

### `app/services/ranker/constraint_audit.py` — `ConstraintAuditor`

Đánh giá mức độ khớp của 1 product với extraction constraints.

```python
audit(extraction: ExtractionResult, product: dict) -> AuditResult
```

**AuditResult fields:**

| Field | Type | Mô tả |
|---|---|---|
| `brand` | MatchState | MATCH / MISMATCH / NOT_SPECIFIED |
| `category` | MatchState | MATCH / MISMATCH / NOT_SPECIFIED |
| `size` | MatchState | MATCH / MISMATCH / NOT_SPECIFIED |
| `packaging` | MatchState | MATCH / MISMATCH / NOT_SPECIFIED |
| `attributes` | MatchState | MATCH / PARTIAL / MISMATCH / NOT_SPECIFIED |
| `attributes_ratio` | float | [0, 1] phần trăm attributes khớp |
| `must_not` | MatchState | MATCH (không vi phạm) / MISMATCH (vi phạm) |
| `hard_pass` | bool | brand + category + must_not đều MATCH-or-NOT_SPECIFIED |
| `soft_pass` | bool | hard_pass + size + packaging |
| `satisfied_count` | int | Số constraint được thỏa |
| `specified_count` | int | Số constraint được chỉ định trong query |

**Matching logic:**
- **Brand:** `normalize_brand(extraction.brand) == normalize_brand(product["brand_norm"])`
- **Category:** `normalize_category(extraction.category) == normalize_category(product["category_norm"])`
- **Size (exact):** `abs(product_ml - extraction_ml) <= max(product_ml * 0.08, 20)`
- **Size (hint):** Dùng `SIZE_HINTS[category]` → large/small threshold
- **Packaging:** `normalize_packaging(extraction.unit_raw) == normalize_packaging(product["packaging"])`
- **Must-not:** Kiểm tra từng token trong `extraction.must_not` không xuất hiện trong `product["name"]`

---

### `app/services/ranker/scorer.py` — `StructuralScorer`

Score mỗi product bằng luật deterministic từ AuditResult + config weights.

```
structural_score = raw_es_score
    + brand_w      (MATCH → +100, MISMATCH → -50)
    + category_w   (MATCH → +50,  MISMATCH → -20)
    + size_w       (MATCH → +30,  MISMATCH → -40)
    + packaging_w  (MATCH → +10,  MISMATCH → -20)
    + attributes_ratio * len(attrs) * 10
    + 1 if is_best_seller
```

Weights được định nghĩa trong `app/core/config.py::RankerConfig`.  
Sort: `structural_score desc`, ties giữ thứ tự ES (stable sort).

---

### `app/services/ranker/decider.py` — `Decider`

Quyết định type và confidence từ scored rows.

#### Gate 1: no_result

```python
if not scored_rows:
    return no_result(confidence=1.0)

if (top.structural_score < MIN_RELEVANCE_SCORE       # 30.0
        and top.audit.satisfied_count == 0
        and top.audit.specified_count >= 1):
    # Người dùng chỉ định thứ gì đó nhưng không có product nào khớp
    return no_result(confidence=sigmoid((MIN - top.score) / 5))
```

#### Gate 2: exact_match

```python
gap_required = gap_exact_threshold (20)      # nếu soft_pass
             | gap_exact_threshold_strict (40) # nếu không soft_pass
if extraction.is_exact_request:
    gap_required = min(gap_required, gap_exact_threshold_explicit)  # 10

is_exact = (
    top.audit.hard_pass
    and gap(top, top2) > gap_required
    and top.audit.satisfied_count / max(specified, 1) >= 0.8
)
```

#### Confidence (unified formula)

```python
base           = sigmoid(gap / 10)
audit_fraction = satisfied / max(specified, 1)
confidence     = 0.5 * base + 0.5 * audit_fraction   # [0.01, 0.99]
```

Confidence là **composite metric** — cao khi đồng thời gap lớn (top-1 nổi bật) và nhiều constraints được thỏa. Không phải penalty-based.

#### Gate 3: needs_clarification (default)

`_top_3_diverse`: pick best_seller → largest_size → smallest_size (unique). Fallback fill từ scored list nếu < 3.

---

### `app/services/ranker/engine.py` — `RankingEngine`

Orchestrator: `decide(extracted, rows, query) → SearchResponse`

1. Empty rows → `_empty_response()` (type=no_result)
2. `StructuralScorer.score(rows, extracted)` → `scored_rows`
3. `Decider.decide(scored_rows, extracted)` → `Decision`
4. `_log_audit(...)` → structured JSON log
5. `_to_response(decision, extracted)` → `SearchResponse`

---

## ES Index Schema (relevant fields)

| Field | Type | Ghi chú |
|---|---|---|
| `id` | keyword | |
| `name` | text (analyzed) | |
| `base_name` | text (analyzed) | Tên gốc không có size/packaging |
| `brand_display` | text (analyzed) | Tên brand để display |
| `brand_norm` | keyword | `normalize_brand(brand)` — dùng để term match |
| `category` | text | |
| `category_norm` | keyword | `normalize_category(category)` |
| `packaging` | keyword | "can", "bottle", "box", … |
| `size_value` | float | |
| `size_unit` | keyword | "ml", "g", "l", … |
| `size_value_ml` | float | Pre-converted to ml (hoặc g cho dry goods) |
| `name_vector` | dense_vector (768) | text-embedding-004 |
| `tags` | keyword[] | Attributes, variants |
| `is_best_seller` | boolean | |

**Quy tắc index:** `brand_norm` và `category_norm` phải được tính tại index-time bằng cùng hàm normalize với query-time (file `app/utils/normalizer.py`).

---

## Config

Tất cả thresholds và weights trong `app/core/config.py`:

```python
class RankerConfig:
    min_relevance_score: float = 30.0
    gap_exact_threshold: int = 20        # khi soft_pass=True
    gap_exact_threshold_strict: int = 40 # khi soft_pass=False
    gap_exact_threshold_explicit: int = 10 # khi is_exact_request=True

SIZE_HINTS: dict = {
    "beverage_bottle":     {"large": 1000, "small": 350},
    "beverage_can":        {"large": 500,  "small": 250},
    "instant_noodle_pack": {"large": 100,  "small": 75},
    "snack":               {"large": 200,  "small": 50},
    "_default":            {"large": 1000, "small": 350},
}
```

---

## Telemetry & Audit Log

Mỗi query ghi 1 JSON line vào `logs/audit.jsonl`:

```json
{
  "ts": "2026-05-16T07:30:00Z",
  "query": "2 lon coca",
  "extraction": {"brand": "coca cola", "quantity": 2, "unit_raw": "lon", ...},
  "top_product": "Coca Cola Original 330ml",
  "audit": {
    "brand": "match", "category": "not_specified",
    "size": "not_specified", "packaging": "match",
    "must_not": "match",
    "satisfied_count": 2, "specified_count": 2,
    "hard_pass": true, "soft_pass": true
  },
  "decision": {
    "type": "exact_match",
    "confidence": 0.87,
    "reason": "hard_pass_gap_32.00",
    "item_ids": ["sku-123"]
  }
}
```
