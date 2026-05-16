# Ranking Pipeline — Benchmark Changelog

---

## 2026-05-16 — Phase 1-3 rebuild (Steps 1–9)

**Score: 51.56% (33/64)** — baseline unchanged; no regression confirmed.

### Thay đổi đã áp dụng (Steps 1–9)

| Step | File | Thay đổi |
|------|------|----------|
| 1-2  | `app/core/config.py` | Đưa weights/thresholds vào `RankerConfig`; thêm `SIZE_HINTS` per-category |
| 2    | `app/utils/normalizer.py` | `normalize_brand`, `normalize_category`, `normalize_packaging`, `normalize_token` |
| 4    | `app/services/ranker/constraint_audit.py` | `ConstraintAuditor` — đánh giá brand/category/size/packaging/must_not per-product |
| 5    | `app/services/ranker/scorer.py` | `StructuralScorer` — deterministic score từ ES + audit weights |
| 6    | `app/services/ranker/decider.py` | `Decider` — AND gate exact_match, no_result threshold, confidence composite |
| 7    | `app/services/ranker/engine.py` | `RankingEngine` rewrite — xoá dead reranker, telemetry log |
| 7.5  | ~~`app/services/ranker/scoring.py`~~ | Xoá (dead code) |
| 7.5  | ~~`app/services/ranker/reranker.py`~~ | Xoá (dead code, never called) |
| 8    | `app/graph/nodes.py` | Bỏ normalize_query_text pre-processing; brand alias post-extraction |
| 9    | `app/services/search/query_builder.py` | Xoá hard size filter; `category_norm` thay `category` |

### Phân tích failure theo nhóm

| Group | Pass/Total | Ghi chú |
|-------|-----------|---------|
| G1 (brand-only) | 7/8 | G1-08 "hảo hảo" fail — brand_norm chưa được reindex |
| G2 (brand+packaging) | 6/8 | G2-05/06 liên quan hảo hảo + "ly" packaging |
| G3 (qty+exact) | **0/14** | Xem root cause bên dưới |
| G4 (category-only) | 6/6 | ✅ 100% |
| G5 (colloquial) | 7/8 | G5-05 "bột giặt" miss omo |
| G6 (variant exclusion) | 2/6 | must_not chưa được LLM extract đủ |
| G7 (no-result) | **0/6** | Xem root cause bên dưới |
| G8 (intent/context) | 5/8 | hảo hảo + exact_match threshold |

### Root cause còn lại (blocking ≥85% target)

#### 1. G3: exact_match gate không fire (19 cases)

Điều kiện exact_match:
```
hard_pass AND gap > gap_required AND audit_fraction >= 0.8
```

**Symptom:** Tất cả G3 trả về `needs_clarification`.

**Nguyên nhân chính:**
- `brand_norm` field trong ES chưa được populate (cần reindex thủ công). Khi brand_norm rỗng, `ConstraintAuditor` compare `wanted_brand` với chuỗi rỗng → `MISMATCH` → `hard_pass=False` → exact gate không thể mở.
- Sau khi reindex: `hard_pass` sẽ đúng. Gap threshold (20) có thể cần tune xuống ~15 nếu catalog đủ diverse.

**Fix cần làm:**
1. **Reindex** (thủ công): chạy `scripts/index_products.py` để populate `brand_norm`, `category_norm`.
2. Sau reindex: chạy lại benchmark để measure.

#### 2. G7: no_result gate không fire (6 cases)

Điều kiện no_result:
```
top.structural_score < MIN_RELEVANCE_SCORE (30)
AND top.audit.satisfied_count == 0
AND top.audit.specified_count >= 1
```

**Symptom:** "iphone", "vitamin C", "áo thun" đều trả `needs_clarification` với conf ~0.90.

**Nguyên nhân:**
- Với query OOC ("iphone"): LLM không extract brand/category → `specified_count=0` → gate condition `specified_count >= 1` không thỏa → gate không fire.
- Structural score vẫn > 30 vì BM25 match partial text trong catalog.

**Fix options (cần investigate sau reindex):**
- Option A: Fire no_result khi `specified_count == 0 AND structural_score < threshold_ooc` (thêm gate riêng cho unstructured query).
- Option B: Prompt engineering — yêu cầu LLM extract category ngay cả khi query rất generic, để `specified_count >= 1`.

#### 3. G1/G3: "hảo hảo" không match (4 cases)

`normalize_brand("hảo hảo")` → `"hao hao"` (strip diacritics).  
ES `brand_norm` field chưa chứa `"hao hao"` vì chưa reindex.  
→ **Fix:** reindex.

#### 4. G6: variant exclusion không hoạt động với implied "thường"

Query "coca thường" → LLM hiện tại không extract `must_not = ["light", "zero", "không đường"]`.  
Đây là prompt engineering issue — LLM cần được hướng dẫn: khi user nói "thường" → infer `must_not` variant keywords.

→ **Fix:** cập nhật extraction prompt để handle implied exclusion.

### Kết luận

Score 52% sau Steps 1–9 **bằng baseline** — không regression, đây là kỳ vọng vì bottleneck chính vẫn là **ES index chưa có `brand_norm`/`category_norm`**. Khi reindex xong, G3 (0/14 → dự báo 10-12/14) và G1 (+1) sẽ cải thiện rõ rệt.

**Estimated post-reindex:** ~70-75% (45-48/64).  
**Remaining gap đến 85%:** G7 no_result (6 cases) + G6 variant exclusion (4 cases) cần thêm work.

---

## Baseline: 2026-05-16 07:19 — 52.0% (33/64)

Trước khi rebuild. Legacy `scoring.py` + hardcoded weights + brand string equality bug + dead reranker.
