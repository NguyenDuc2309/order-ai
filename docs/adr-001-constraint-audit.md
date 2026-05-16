# ADR-001: Thay thế legacy scoring bằng Constraint Audit + AND Gate

**Date:** 2026-05-16  
**Status:** Accepted  
**Deciders:** mbw1  

---

## Context

Pipeline cũ (`app/services/ranker/scoring.py` + `engine.py`) có 3 bug nghiêm trọng dẫn đến benchmark 52%:

### Bug 1: Brand match luôn fail

```python
# scoring.py (cũ)
brand_ok = product["brand"].lower() == extraction.brand.lower()
```

`product["brand"]` thường là display name ("Coca-Cola", "Hảo Hảo") trong khi `extraction.brand` từ LLM là text thô ("coca cola", "hao hao"). String equality không bao giờ đúng khi có dấu/dấu câu/khoảng trắng khác nhau.

**Hậu quả:** `brand_ok=False` → score bị trừ 50 → exact_match impossible → toàn bộ G3 fail.

### Bug 2: no_result không fire

```python
# engine.py (cũ)
if not rows:
    return no_result_response
# else: luôn trả về exact hoặc clarify
```

ES hybrid search (kNN) luôn trả về rows kể cả khi catalog không có product liên quan. "iphone" vẫn get top-20 results → no_result gate chưa bao giờ fire.

### Bug 3: Confidence arbitrary

```python
# engine.py (cũ)
base_conf = sigmoid(gap / 10)
if not brand_ok:
    conf = base_conf * 0.7   # penalty không có basis toán học
```

Confidence không phản ánh chất lượng match mà chỉ là penalty từ Bug 1.

### Dead code

`GeminiReranker` được instantiate nhưng không bao giờ được gọi. Tạo latency trong `__init__` (API client init) không có lợi ích.

---

## Decision

Thay toàn bộ bằng **Constraint Audit + AND Gate** pattern:

### 1. Normalize trước khi match

```
normalize_brand("Coca-Cola") == normalize_brand("coca cola") == "coca cola"
```

Cùng 1 hàm normalize cho index-time và query-time. Brand match = keyword equality trên normalized form.

### 2. Constraint Audit per product

Thay vì tính 1 score tổng, audit từng constraint riêng:
- brand: MATCH / MISMATCH / NOT_SPECIFIED
- category, size, packaging, attributes, must_not

**Lý do:** Audit riêng lẻ cho phép AND gate chính xác. Legacy code mix hết vào 1 score làm mờ signal.

### 3. AND gate cho exact_match

```
exact_match = hard_pass AND gap > threshold AND audit_fraction >= 0.8
```

Không dùng threshold trên tổng score (dễ bị dominated bởi ES BM25 noise). AND gate đảm bảo tất cả hard constraints phải pass.

### 4. no_result từ score threshold + constraint check

```
no_result = score < MIN_RELEVANCE AND satisfied=0 AND specified>=1
```

Fire khi: user chỉ định constraint nhưng không constraint nào match + ES score thấp.

### 5. Confidence composite

```
confidence = 0.5 * sigmoid(gap/10) + 0.5 * audit_fraction
```

Hai signal độc lập: gap (top-1 nổi bật so với top-2) + audit_fraction (bao nhiêu % constraints khớp). Không phải penalty.

---

## Alternatives Considered

### Alt A: Giữ legacy scoring, chỉ fix brand match

- Fix nhanh hơn
- Nhưng: magic numbers (+100/-50/+30/-40) không có basis; confidence vẫn sai; dead code vẫn còn; no_result vẫn không fire đúng

### Alt B: Full ML reranker (Gemini API call)

- Chính xác hơn cho edge cases
- Nhưng: +300-500ms latency; không thể debug/audit; không deterministic; phụ thuộc quota Gemini
- Quyết định: **defer đến khi có ≥500 production query có label**

### Alt C: Tăng số lượng test cases

- Không fix bug, chỉ làm benchmark dễ hơn
- Rejected: không giải quyết root cause

---

## Consequences

**Positive:**
- Brand match đúng với mọi text encoding variant
- exact_match gate có thể audit được (biết lý do fail)
- Confidence có ý nghĩa thực sự (không phải penalty)
- Dead code (reranker) đã được xoá
- Mỗi query có audit log → debuggable

**Negative:**
- Cần reindex để có `brand_norm`/`category_norm` fields (1 lần, thủ công)
- `no_result` với `specified_count=0` vẫn chưa được xử lý (defer: xem ADR-002 khi implement)
- G6 variant exclusion ("thường" → implied must_not) cần prompt engineering (scope riêng)

**Neutral:**
- Score 52% sau Steps 1-9 bằng baseline — expected vì bottleneck là reindex chưa chạy
- Post-reindex: dự báo ~70-75%

---

## Files Affected

| File | Action |
|---|---|
| `app/services/ranker/scoring.py` | DELETED |
| `app/services/ranker/reranker.py` | DELETED |
| `app/services/ranker/constraint_audit.py` | NEW |
| `app/services/ranker/scorer.py` | NEW |
| `app/services/ranker/decider.py` | NEW |
| `app/services/ranker/engine.py` | REWRITE |
| `app/utils/normalizer.py` | NEW |
| `app/core/config.py` | EDIT (weights + SIZE_HINTS) |
| `app/services/search/query_builder.py` | EDIT (remove hard size filter, category_norm) |
| `app/graph/nodes.py` | EDIT (brand alias post-extraction, telemetry) |
| `scripts/index_products.py` | EDIT (brand_norm, category_norm fields) |
