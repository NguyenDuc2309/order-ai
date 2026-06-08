# Problem List — Order-AI

> Hàng đợi công việc. Khung neo và nguyên tắc (P-x): xem `docs/development-plan.md`.
> Mỗi issue ghi **phạm vi đầy đủ** (mọi file phải đụng) — xử lý là xử lý trọn, không vá lẻ.

**Mức độ:**
- **P0** — corrupt quyết định hoặc làm benchmark vô nghĩa
- **P1** — sai trực tiếp chất lượng search ở nhiều case
- **P2** — logic sai, tác động hẹp / kiến trúc cần thiết kế lại
- **P3** — dead code / tech debt

**Bối cảnh vector store:** index `products` — 1700 sản phẩm, 100% có `name_vector`.

---

## P0

### PROB-001 — Taxonomy category: hai nguồn + fallback rác

**Nguyên tắc:** P5 (một nguồn taxonomy), P2 (dùng `mch` cấu trúc).

**Mô tả:** Khâu index sai:
- **Hai nguồn taxonomy:** `_CATEGORY_RULES` trong `scripts/index_products.py` (22 category) và
  danh sách category trong `extraction_v1.yaml` (16) — hand-synced, vi phạm P5.
- **Fallback rác:** `_map_category()` khi không khớp keyword nào thì
  `return row.get("mch4") or row.get("mch3") or "Other"` → tạo ~20 giá trị `category_norm` rác.
  Xác nhận trên ES: `lon (heo)` (23 doc), `thuy hai san so che` (19), `thuc pham đong hop` (16),
  `thit nguoi` (3), `tham` (1)… Hàng trăm sản phẩm mang category vô nghĩa → audit MISMATCH sai.
- **Keyword-guess thay vì dùng `mch`:** `_map_category` so khớp keyword trên text `mch2-5 + name`.
  Nhưng `mch1-5` *đã là* cây category cấu trúc — vi phạm P2, đáng lẽ map `mch` → category
  bằng lookup, không đoán bằng keyword.

**Phạm vi:**
- Tạo một file taxonomy chung (single source of truth): map `mch` → `category_norm`.
- `scripts/index_products.py` — `_map_category` dùng lookup từ `mch`, bỏ fallback rác.
- `app/prompts/extraction_v1.yaml` — category list tham chiếu cùng nguồn.
- `app/services/ranker/constraint_audit.py` — audit dùng cùng vocabulary.
- Re-index (user chạy thủ công) + verify `category_norm` chỉ còn giá trị hợp lệ.

---

### PROB-003 — Unit test là theater

**Nguyên tắc:** 6.1.

**Mô tả:** 16 test chạy 0.03s, toàn mock. Không test nào chạm ES/Gemini/pipeline thật.
PROB-001/021 sống sót vì test không bắt được.

**Phạm vi:**
- Viết integration test chạy 4 tầng với fixture catalog nhỏ.
- Test phải bắt: taxonomy mismatch, variant leak, `no_result` đúng/sai.

---

### PROB-020 — Benchmark không đo được correctness

**Nguyên tắc:** 6.1.

**Mô tả:** DSL chấm điểm coi `no_result` là output luôn hợp lệ cho mọi case kỳ vọng
`exact`/`clarify` ("catalog có thể chưa index"). Hệ quả: một hệ thống trả `no_result`
cho TẤT CẢ query non-G7 vẫn đạt ~100%. Score 100% hiện tại chỉ chứng minh "không
hallucinate", KHÔNG chứng minh "tìm đúng sản phẩm". Type mismatch `exact↔clarify` cũng
chỉ informational. Benchmark vì vậy không phát hiện được PROB-021.

**Phạm vi:**
- `scripts/test_cases.md` — mỗi case ghi rõ sản phẩm có/không trong catalog (ground truth).
- `scripts/benchmark.py` — nếu case có sản phẩm trong catalog mà actual=`no_result` → FAIL.
- Cân nhắc: gate `exact` thành strict cho nhóm G3 Full-spec.

---

## P1

### PROB-021 — `no_result` bắn nhầm vào sản phẩm có thật

**Nguyên tắc:** P1.

**Mô tả:** 3 gate `no_result` (attribute gate, brand-mismatch gate, bigram coverage gate)
trả `no_result` cho sản phẩm tồn tại trong catalog:
- `cho tôi hộp sữa nhỏ vinamilk` → `no_result`. LLM bóc `attributes=['nhỏ']` ("nhỏ" là
  từ chỉ size, không phải thuộc tính sản phẩm); attribute gate không thấy "nhỏ" trong tên
  top-5 → `no_result`. Cùng sản phẩm, `sữa hộp vinamilk` lại ra `needs_clarification` đúng.
- `mì tôm` → `no_result`. Bigram "mì tôm" không xuất hiện literal trong tên SP ("Mì xào…",
  "Mì Koreno…") dù mì gói có thật trong catalog.
- `tương ớt`, `sữa tươi ít béo`, `sting đỏ`, `bò húc` — tương tự.

Nguyên nhân kép: (a) LLM over-extract từ chỉ size/category-noun thành `attributes`;
(b) gate so khớp literal substring thay vì semantic. Score 100% che được vì PROB-020.

**Phạm vi:**
- `app/prompts/extraction_v1.yaml` — cấm bóc từ chỉ size ("nhỏ", "lớn", "vừa") vào
  `attributes`; chúng thuộc `size_hint`.
- `app/services/ranker/decider.py` — attribute/bigram gate không được dựa vào khớp literal
  tên sản phẩm; dùng tín hiệu structural (category match, score) thay thế.

---

### PROB-006 — Extraction degradation vô hình

**Nguyên tắc:** P1.

**Mô tả:** LLM trả output partial/fallback → hệ thống dùng default âm thầm, `confidence`
không phản ánh việc extraction đã hỏng.

**Phạm vi:**
- `app/models/extraction.py` — thêm tín hiệu chất lượng extraction.
- `app/services/ranker/decider.py` — tích hợp vào confidence.

---

## P2

### PROB-008 — Confidence formula conflate hai trục

**Mô tả:** `confidence = 0.5*sigmoid(gap/10) + 0.5*audit_fraction` — trộn separability và
match quality với weight tùy tiện + magic `/10`.

**Phạm vi:** `decider.py` — tách 2 signal riêng, dùng AND gate thay vì average.

---

### PROB-009 — Variant token hard-coded

**Nguyên tắc:** P2.

**Mô tả:** Đã sửa substring → word-boundary regex. Nhưng `VARIANT_TOKENS` vẫn là list
hard-code trong `scorer.py`. Variant là thuộc tính sản phẩm — nên là metadata index-time.

**Phạm vi:** `index_products.py` — thêm `is_variant`/`variant_type` lúc index;
`scorer.py`/`decider.py` đọc từ product metadata.

---

### PROB-010 — `needs_clarification` = top-K thuần

**Mô tả:** `needs_clarification` chỉ trả top-3, không cho client biết "mơ hồ ở chiều nào".
`_top_3_diverse` chọn theo size lớn/nhỏ → kéo cả sản phẩm lạc loài (vd `tiger lon` ra
"Màu nước Thiên Long").

**Phạm vi:** `decider.py` + `models/response.py` — thêm `ambiguous_dimension`; sửa
diverse-pick để không kéo sản phẩm ngoài category.

---

### PROB-011 — Duplicate ranking signal

**Mô tả:** ES query boost `brand^60`/`category_norm^30` + StructuralScorer cộng +100/+50 cho
cùng tín hiệu → brand bị amplify quá mức.

**Phạm vi:** `query_builder.py` — bỏ soft boost brand/category (chỉ giữ để recall), để
StructuralScorer quyết định ranking.

---

## P3

### PROB-014b — `pack_count` không ai dùng

**Mô tả:** `pack_count` được index, `es_service.py` đọc vào dict, nhưng không tầng nào dùng.

**Phạm vi:** Quyết định: dùng nó (phân biệt thùng/lốc) hay gỡ khỏi index + es_service.

---

---

### PROB-022 — UOM=thùng không filter ra sản phẩm thùng

**Nguyên tắc:** P1.

**Mô tả:** Các query có `uom=thùng` rõ ràng (`heineken thùng`, `2 thùng bia heineken`,
`thùng 24 lon tiger`) đều trả về items không có dạng thùng trong top-3. Catalog có sản
phẩm thùng (`10012012T24`, `10170930T24`), nhưng pipeline không filter/boost đúng.
Xác nhận: G2-04, G3-02, G3-07 FAIL vì `required 'thùng' not in top results`.

Root cause có thể là một trong ba: (a) extractor không bóc `uom=thung` từ "thùng";
(b) query builder không dùng uom để filter/boost ES; (c) ranker không penalize sản
phẩm không có uom khớp. Cần trace extraction log để xác định.

**Phạm vi:**
- `app/prompts/extraction_v1.yaml` — verify `thùng` → `uom: thung` đúng.
- `app/services/query_builder.py` — uom phải là filter hoặc strong boost, không bỏ qua.
- `app/services/ranker/constraint_audit.py` — audit phải penalize sản phẩm sai uom khi uom được extract.

---

## P0 — Eval Infrastructure

### PROB-023 — `eval_gate.py` Decision Type Accuracy luôn báo ~0.094 (bug)

**Nguyên tắc:** P0 — metric sai làm mọi quyết định đều sai.

**Mô tả:** `compute_mft_metrics` so sánh `expected_type` với string `"exact"` và `"clarify"`:
```python
elif expected in ("exact", "clarify"):
```
Nhưng benchmark.py ghi `expected_type` vào JSON là `"exact_match"` và
`"needs_clarification"` — không bao giờ khớp. Chỉ nhánh `no_result` chạy → DTA = 5/53
= 0.094 bất kể pipeline tốt hay xấu.

Giá trị thực (nếu fix): cần tính lại — 27/53 type-match trong benchmark JSON là điểm
khởi đầu, nhưng đó là logic lỏng (benchmark cho PASS khi type mismatch nếu items đúng).
Sau khi fix eval_gate, DTA thực có thể thấp hơn 0.51 vì nhiều case G1-G3 pipeline trả
`no_result` dù expected `needs_clarification`.

**Phạm vi:**
- `scripts/eval_gate.py` — đổi `expected in ("exact", "clarify")` →
  `expected in ("exact", "clarify", "exact_match", "needs_clarification")`, và map
  `clarify` → match cả `needs_clarification`.
- Re-run eval_gate sau fix để có DTA thực.

---

*Cập nhật: 2026-06-08.*
