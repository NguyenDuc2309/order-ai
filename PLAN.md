# Order-AI Ranking Pipeline — Rebuild Plan

> Mục tiêu: viết lại toàn bộ ranking + decision pipeline trên nền constraint audit
> + AND gate, fix các bug hiện tại, đập bỏ dead code, mở khoá AI signals đang bị
> ignore. Confidence vẫn được trả về trong API response (phục vụ benchmark).
>
> **Baseline:** benchmark 52% (33/64) — `reports/2026-05-16_07-19-10_score-52pct.json`
> **Target:** ≥85% sau Phase 1-3, ≥90% sau Phase 4 (tuning).

---

## 1. Vấn đề cần fix (mapping bug → giải pháp)

| Bug | Vị trí hiện tại | Giải pháp |
|---|---|---|
| Brand match strict equality (`"coca cola" != "coca-cola"`) | `scoring.py:22`, `engine.py:51` | Normalize brand ở index time + query time qua `app/utils/normalizer.py` |
| `no_result` chỉ fire khi ES rỗng → out-of-catalog trả rác | `engine.py:21-28` | `Decider` thêm `MIN_RELEVANCE_SCORE` threshold + audit "không constraint nào match" |
| Confidence 41% arbitrary từ `base_conf * 0.7` | `engine.py:63` | Confidence rebuild từ constraint audit fraction + score gap, không phải penalty |
| `is_exact_request` từ LLM bị ignore | `extraction.py:17`, `engine.py:76` | `Decider` dùng làm soft hint giảm gap threshold khi user nói rõ |
| Reranker là code chết, instantiate nhưng không gọi | `engine.py:13`, `reranker.py` | Xoá toàn bộ |
| `_top_three_diverse` có thể trả về < 3 items | `engine.py:115-130` | Fallback fill từ scored list nếu chưa đủ 3 |
| Magic numbers (gap=20/40, score+100/-50, 0.95+0.04) | `scoring.py`, `engine.py` | Đẩy vào `app/core/config.py` |
| Synonym normalize chạy TRƯỚC extraction, có thể bóp méo input LLM | `nodes.py:26` | Bỏ pre-processing, dùng synonym ở post-extraction (normalize brand output) |
| Hard size filter ±8% trong ES query | `query_builder.py` | Chuyển thành soft boost penalty |
| Không có telemetry — không debug được sau production | toàn pipeline | Structured JSON log per query với constraint audit dump |

---

## 2. Kiến trúc mới

```
app/
├── utils/
│   ├── normalizer.py          [NEW]   normalize_brand, normalize_token
│   ├── synonyms.py            [EDIT]  bỏ pre-processing query
│   └── text_norm.py           [keep]
│
├── services/ranker/
│   ├── __init__.py            [EDIT]
│   ├── constraint_audit.py    [NEW]   ConstraintAuditor — đếm field match/mismatch
│   ├── scorer.py              [NEW]   StructuralScorer — deterministic rule scoring
│   ├── decider.py             [NEW]   Decider — type + confidence quyết định
│   ├── engine.py              [REWRITE] orchestrate audit → score → decide
│   ├── scoring.py             [DELETE]
│   └── reranker.py            [DELETE]
│
├── services/search/
│   └── query_builder.py       [EDIT]  soft filter cho size, dùng brand normalized
│
├── core/
│   └── config.py              [EDIT]  weights/thresholds/min_relevance
│
├── graph/
│   └── nodes.py               [EDIT]  bỏ normalize_query_text, thêm telemetry log
│
└── models/
    └── extraction.py          [keep — is_exact_request đã có]
```

```
scripts/
├── index_products.py          [EDIT]  index brand normalized (brand_norm field)
├── benchmark.py               [keep]
└── test_cases.md              [keep]
```

### Flow mới

```
Query
  │
  ▼
[extract_node]
  ├─ Gemini extractor → ExtractionResult (brand, qty, size, is_exact_request…)
  ├─ Gemini embed     → query_vector
  └─ Post-normalize   → normalize_brand(extraction.brand)
  │
  ▼
[build_query_node] → hybrid ES query (kNN + BM25), brand = normalized term
  │
  ▼
[search_node] → top-K rows từ ES
  │
  ▼
[decide_node]
  │
  ├─ ConstraintAuditor.audit(extraction, top_1)
  │     → AuditResult { brand: match/mismatch/na, category, size, packaging,
  │                     attributes, must_not, qty, score_signal }
  │
  ├─ StructuralScorer.score(rows, extraction)
  │     → scored_rows (deterministic boost theo audit của từng product)
  │
  └─ Decider.decide(audit, scored_rows, extraction)
        │
        ├─ Check no_result gate (low score AND no constraint match) → no_result
        ├─ Check exact gate    (AND of hard constraints + gap + is_exact hint) → exact_match
        └─ else → needs_clarification (top 3 diverse, fallback fill)
  │
  ▼
SearchResponse { type, confidence, items, message }
```

---

## 3. Phase 1 — Foundation (P0, 1 step)

### Step 1: Config + telemetry + cleanup

- [x] **1.1** `app/core/config.py` — thêm dataclass `RankerConfig` với fields:
  - `min_relevance_score: float = 30.0`
  - `gap_exact_threshold: int = 20`
  - `gap_exact_threshold_strict: int = 40`  *(khi audit không pass hết)*
  - `gap_exact_threshold_explicit: int = 10`  *(khi `is_exact_request=True`)*
  - `weight_brand_match: float = 100.0`
  - `weight_brand_miss: float = -50.0`
  - `weight_category_match: float = 50.0`
  - `weight_category_miss: float = -20.0`
  - `weight_size_match: float = 30.0`
  - `weight_size_miss: float = -40.0`
  - `weight_packaging_match: float = 10.0`
  - `weight_packaging_miss: float = -20.0`
  - `weight_attribute: float = 10.0`
  - `weight_best_seller: float = 1.0`
- [x] **1.2** Setup structured logger `orderresolve.audit` với JSON handler ghi file `logs/audit.jsonl`
- [x] **1.3** Setup test scaffolding:
  - Tạo `tests/__init__.py` (rỗng)
  - Tạo `tests/conftest.py` với fixture chung (sample extraction, sample ES rows)
  - Tạo `requirements-dev.txt` thêm `pytest>=8.0`, `pytest-asyncio` (nếu cần)
  - Tạo `pytest.ini` hoặc `pyproject.toml` section `[tool.pytest.ini_options]` với `testpaths = ["tests"]`
- [x] **1.4** Xoá import `GeminiReranker` ở `engine.py:5` và field `self.reranker` ở `engine.py:13`
- [x] **1.5** Xoá file `app/services/ranker/reranker.py` (sau khi import đã được dọn ở 1.4)
- [x] **1.6** Smoke test: `python -c "import app.services.ranker.engine; import app.core.config"` không lỗi; `pytest tests/ -q` chạy (0 test cũng pass)

**Acceptance:**
- `python -c "from app.core.config import RankerConfig; print(RankerConfig())"` in ra đầy đủ field
- `app/services/ranker/reranker.py` không tồn tại
- `pytest tests/` exit code 0
- `logs/audit.jsonl` được tạo khi chạy 1 lần `pipeline.invoke(...)` smoke

---

## 4. Phase 2 — Normalizer + Reindex (P0, 2 steps)

### Step 2: Normalizer module

- [x] **2.1** Tạo `app/utils/normalizer.py`:
  ```python
  def normalize_brand(s: str | None) -> str:
      """Lower + strip diacritics + remove [-_./] + collapse spaces. None → ''."""

  def normalize_category(s: str | None) -> str:
      """Same rule as normalize_brand — categories cũng là keyword field trong ES."""

  def normalize_token(s: str | None) -> str:
      """Lower + strip diacritics + collapse spaces (giữ dấu cách giữa từ)."""

  def normalize_packaging(s: str | None) -> str:
      """Map đồng nghĩa packaging về dạng chuẩn:
         lon/can → can; chai/bottle → bottle; thùng/case → case;
         hộp/box → box; gói/pack/bag → pack; ly/cup → cup; túi → bag."""
  ```
- [x] **2.2** Tạo `tests/test_normalizer.py` với cases:
  - `normalize_brand("Coca-Cola")` == `"coca cola"`
  - `normalize_brand("COCA COLA")` == `"coca cola"`
  - `normalize_brand("Hảo Hảo")` == `"hao hao"`
  - `normalize_brand("TH true MILK")` == `"th true milk"`
  - `normalize_brand(None)` == `""`
  - `normalize_category("Nước Giải Khát")` == `"nuoc giai khat"`
  - `normalize_packaging("lon")` == `"can"`; `normalize_packaging("ly")` == `"cup"`
  - `normalize_packaging("THÙNG")` == `"case"`; `normalize_packaging(None)` == `""`

**Acceptance:** `pytest tests/test_normalizer.py -v` pass 100%.

### Step 3: Index normalized brand

- [x] **3.1** `scripts/index_products.py:181` — thêm field `brand_norm` (keyword) = `normalize_brand(brand)` và `category_norm` (keyword) = `normalize_category(category)`; giữ nguyên `brand`, `brand_display`, `category` cho hiển thị
- [ ] **3.2** Reindex toàn bộ: `python scripts/index_products.py --reset`
- [ ] **3.3** Verify: 2 ES query test
  ```
  GET /products/_search { "query": { "term": { "brand_norm":    "coca cola" } } }
  GET /products/_search { "query": { "term": { "category_norm": "nuoc giai khat" } } }
  ```
  → mỗi query trả ≥1 hit

**Acceptance:** ES có ≥1 hit cho `brand_norm` của top 10 brand (coca cola, pepsi, tiger, heineken, vinamilk, lavie, omo, hao hao, sting, oishi) và ≥1 hit cho ≥3 category phổ biến trong catalog.

**Lý do bỏ brand_aliases:**
- "Coca-Cola" / "COCA COLA" / "coca cola" → `normalize_brand()` đã xử lý
- "coca" → "Coca Cola" → BM25 fuzziness trong QueryBuilder lo
- "bò húc" → "Red Bull", "coke" → "Coca Cola" → xử lý ở Step 8 qua synonym dict apply **sau** extraction trên field `extraction.brand` (không bóp méo query input cho LLM)

---

## 5. Phase 3 — ConstraintAuditor + StructuralScorer (P0, 2 steps)

### Step 4: ConstraintAuditor

- [x] **4.1** Tạo `app/services/ranker/constraint_audit.py`:
  ```python
  from enum import Enum
  from dataclasses import dataclass

  class MatchState(str, Enum):
      MATCH = "match"
      MISMATCH = "mismatch"
      PARTIAL = "partial"           # dùng cho attributes (matched N/M)
      NOT_SPECIFIED = "not_specified"

  @dataclass
  class AuditResult:
      brand: MatchState
      category: MatchState
      size: MatchState
      packaging: MatchState
      attributes: MatchState             # MATCH/PARTIAL/MISMATCH/NOT_SPECIFIED
      attributes_ratio: float            # matched / total user-specified (0.0..1.0)
      must_not: MatchState               # MATCH = không có forbidden term nào
      qty_extracted: int                 # always >= 1
      hard_pass: bool                    # brand + category + must_not all in {MATCH, NOT_SPECIFIED}
      soft_pass: bool                    # hard_pass AND size + packaging in {MATCH, NOT_SPECIFIED}
      satisfied_count: int               # số field == MATCH (cho fraction)
      specified_count: int               # số field user nói tới (≠ NOT_SPECIFIED)
  ```
  Quy ước: `hard_pass` xem `NOT_SPECIFIED` là pass (vì user không yêu cầu); chỉ MISMATCH mới làm fail.

- [x] **4.2** `ConstraintAuditor.audit(extraction, product) -> AuditResult`:
  - **Brand:** `normalize_brand(extraction.brand)` vs `product["brand_norm"]` (sau khi đã `resolve_brand_alias` ở Step 8)
  - **Category:** `normalize_category(extraction.category)` vs `product["category_norm"]`
  - **Size:** logic `size_match` cũ (giữ tolerance ±8% hoặc ±20ml)
  - **Packaging:** `normalize_packaging(extraction.unit_raw)` vs `normalize_packaging(product["packaging"])`
  - **Attributes:** đếm matched/total qua tags + haystack. Trả `attributes_ratio = matched / total`. State: `MATCH` nếu ratio==1.0, `PARTIAL` nếu 0<ratio<1, `MISMATCH` nếu ratio==0, `NOT_SPECIFIED` nếu `extraction.attributes == []`
  - **must_not:** check `extraction.must_not` token nào xuất hiện trong `normalize_token(product["name"])` không. MATCH = không có. NOT_SPECIFIED nếu list rỗng.
- [x] **4.3** Tests `tests/test_constraint_audit.py`:
  - "2 lon coca" + product "Coca Cola lon 330ml" → hard_pass=True
  - "2 lon coca" + product "Coca Cola Light lon 330ml" với extraction.must_not=["light"] → must_not=MISMATCH
  - "iphone" + product "Sữa tắm Lux" → all NA/mismatch, satisfied=0, specified ≥1

**Acceptance:** test pass; audit dump (JSON) có thể đọc được từ log.

### Step 5: StructuralScorer

- [x] **5.1** Tạo `app/services/ranker/scorer.py`:
  - `StructuralScorer.score(rows, extraction) -> list[ScoredRow]`
  - Mỗi row: gọi `ConstraintAuditor.audit(extraction, product)` rồi cộng/trừ score theo `RankerConfig` weights
  - Không hardcode magic number — đọc từ `config.ranker`
  - Trả ScoredRow gồm `product, raw_es_score, structural_score, audit (AuditResult)`
- [x] **5.2** Sort theo `structural_score` desc, ổn định
- [x] **5.3** Tests `tests/test_scorer.py`:
  - Brand match cộng đúng `weight_brand_match`
  - Brand mismatch trừ đúng `weight_brand_miss`
  - Best seller tie-break hoạt động

> **Lưu ý:** KHÔNG xoá `scoring.py` ở step này — `engine.py` vẫn còn import nó cho đến Step 7. Việc xoá file cũ chuyển sang Step 7.5.

**Acceptance:** test pass; điểm số deterministic, có thể reproduce; cả `scoring.py` (cũ) và `scorer.py` (mới) cùng tồn tại song song.

---

## 6. Phase 4 — Decider (P0, 1 step)

### Step 6: Decider với AND gate

- [x] **6.1** Tạo `app/services/ranker/decider.py`:
  ```python
  @dataclass
  class Decision:
      type: Literal["exact_match", "needs_clarification", "no_result"]
      confidence: float
      reason: str          # text reason (cho audit log)
      items: list[ScoredRow]
  ```
- [x] **6.2** `Decider.decide(scored_rows, extraction) -> Decision` với logic:

  **Gate 1 — no_result:**
  ```
  if not scored_rows: → no_result, confidence=1.0  (catalog rỗng → chắc chắn)
  top = scored_rows[0]
  if top.structural_score < MIN_RELEVANCE_SCORE
     AND top.audit.satisfied_count == 0
     AND top.audit.specified_count >= 1:
      → no_result
      # Score càng thấp → càng chắc chắn không khớp → conf càng cao
      confidence = sigmoid((MIN_RELEVANCE_SCORE - top.structural_score) / 5)
  ```

  **Gate 2 — exact_match (AND of):**
  ```
  hard_pass        = top.audit.hard_pass (brand + category + must_not)
  gap_required     = config.gap_exact_threshold        if top.audit.soft_pass
                   = config.gap_exact_threshold_strict if not soft_pass
  if extraction.is_exact_request:
      gap_required = min(gap_required, config.gap_exact_threshold_explicit)

  is_exact = (
      hard_pass AND
      gap(top, top2) > gap_required AND
      top.audit.satisfied_count / max(top.audit.specified_count, 1) >= 0.8
  )
  ```

  **Confidence (chung cho cả exact và clarify):**
  ```
  base = sigmoid(gap / 10)
  audit_fraction = satisfied / max(specified, 1)
  confidence = 0.5 * base + 0.5 * audit_fraction   # composite, không phải penalty
  ```
  *(Dùng 1 công thức duy nhất — tránh tunable param không có dữ liệu để justify.)*

  **Gate 3 — clarify (default):**
  ```
  items = top_3_diverse(scored_rows) với fallback fill từ next-best
  confidence = công thức trên
  ```

- [x] **6.3** Helper `_top_3_diverse(rows)` với fallback fill:
  - Pick best_seller, largest_size, smallest_size (unique)
  - Nếu < 3 → fill từ scored list theo thứ tự score desc
  - Guarantee return 3 items khi `len(rows) >= 3`
- [x] **6.4** Tests `tests/test_decider.py`:
  - "2 lon coca" với hard_pass=True, gap=30, audit 4/4 → exact_match conf >= 0.85
  - "iphone" → no_result conf < 0.3
  - "coca cola" brand-only → needs_clarification (gap nhỏ, audit 1/1 nhưng không có size/qty rõ)

**Acceptance:** test pass; G3 + G7 case mock đều ra đúng type.

---

## 7. Phase 5 — Engine + Pipeline integration (P0, 2 steps)

### Step 7: Rewrite RankingEngine

- [x] **7.1** Rewrite `app/services/ranker/engine.py`:
  ```python
  class RankingEngine:
      def __init__(self):
          self.auditor  = ConstraintAuditor()
          self.scorer   = StructuralScorer()
          self.decider  = Decider()

      def decide(self, extracted, rows, original_query=""):
          if not rows:
              return self._empty_response()
          scored = self.scorer.score(rows, extracted)
          decision = self.decider.decide(scored, extracted)
          self._log_audit(extracted, scored[0], decision, original_query)
          return self._to_response(decision, extracted)
  ```
- [x] **7.2** `_to_response` map Decision → SearchResponse, set `quantity = extracted.quantity` cho items
- [x] **7.3** `_log_audit` ghi JSON line vào `logs/audit.jsonl`:
  ```json
  {"ts":"…","query":"2 lon coca","extraction":{…},"top_product":"…",
   "audit":{"brand":"match",…,"satisfied":4,"specified":4},
   "decision":{"type":"exact_match","confidence":0.87,"reason":"hard_pass+gap=32"}}
  ```
- [x] **7.4** Tests `tests/test_engine.py` integration với mock ES rows
- [x] **7.5** Xoá `app/services/ranker/scoring.py` (engine.py mới đã không còn import nó)

**Acceptance:** engine làm việc end-to-end với mock, log file populated, `scoring.py` không còn tồn tại.

### Step 8: Pipeline cleanup

- [x] **8.1** `app/graph/nodes.py:26` — bỏ `normalize_query_text(state["query"])` khỏi pipeline pre-processing (không bóp méo query input của LLM)
- [x] **8.2** Refactor `app/utils/synonyms.py`: đổi tên hàm thành `resolve_brand_alias(brand: str) -> str` chỉ apply trên brand đã extract (vd `"bò húc"` → `"red bull"`, `"coke"` → `"coca cola"`)
- [x] **8.3** Trong `extract_node` (`nodes.py`): sau khi `extractor.extract()` trả về, apply `resolve_brand_alias(extraction.brand)` rồi `normalize_brand(...)` trước khi truyền xuống `build_query_node`
- [x] **8.4** Thêm telemetry log cho mỗi node (latency, output size, brand resolution: raw → alias → normalized)

**Acceptance:** end-to-end test với benchmark precheck (5 cases) chạy không lỗi.

---

## 8. Phase 6 — QueryBuilder + Search improvements (P1, 1 step)

### Step 9: Bỏ hard filter size + dùng brand_norm/category_norm

- [x] **9.1** `app/services/search/query_builder.py` — **bỏ hoàn toàn** hard size filter (`filter: range`). Recall sẽ tăng (kéo về cả sản phẩm out-of-tolerance), nhưng StructuralScorer đã có `size_match` để boost/penalize điểm sau đó → không cần filter trùng ở ES.
- [x] **9.2** Brand match dùng `term: brand_norm` thay vì `term: brand`; category match dùng `term: category_norm`
- [x] **9.3** Tune size_hint thresholds theo category trong `app/core/config.py`:
  ```python
  SIZE_HINTS = {
      "beverage_bottle":     {"large": 1000, "small": 350},
      "beverage_can":        {"large": 500,  "small": 250},
      "instant_noodle_pack": {"large_g": 100,"small_g": 75},
      # default fallback (như cũ)
      "_default":            {"large": 1000, "small": 350},
  }
  ```
  Map category → hint bucket (đơn giản qua dict lookup). `ScoringRanker.size_match` đọc hint phù hợp.

**Acceptance:** "coca 320ml" tìm được "Coca Cola 320ml" (trước bị filter 8% loại); benchmark G3 không regress so với Step 7.

---

## 9. Phase 7 — Validation (P0, 1 step)

### Step 10: Run benchmark, fix regressions

- [x] **10.1** Chạy `python scripts/benchmark.py --no-confirm` với test_cases.md hiện tại (64 cases)
- [x] **10.2** Phân tích report mới, đối chiếu với baseline 52%:
  - G3 phải đạt ≥ 10/14 ← **0/14** (cần reindex `brand_norm`)
  - G7 phải đạt ≥ 4/6  ← **0/6** (cần fix no_result gate cho `specified_count=0`)
  - G1 + G2 + G4 không regress ← **G4 6/6 ✅, G1 7/8, G2 6/8** — không regress
- [x] **10.3** Nếu fail cases cụ thể → patch — root cause documented; fix phụ thuộc reindex (thủ công)
- [x] **10.4** Document final score trong `reports/CHANGELOG.md` (link report JSON + summary)

**Acceptance:** Benchmark ≥ 85%. Nếu < 85%, dừng lại analyze trước khi tiếp tục.

---

## 10. Phase 8 — Documentation (P1, 1 step)

### Step 11: Architecture docs

- [x] **11.1** Thêm `docs/ranker-architecture.md` mô tả flow + diagram (markdown)
- [x] **11.2** Thêm `docs/adr-001-constraint-audit.md` — ADR cho quyết định bỏ scoring cũ
- [x] **11.3** Update README với link đến doc mới + dòng "Latest benchmark score: XX% (link đến report JSON mới nhất)"
- [x] **11.4** Comment-doc cho mỗi class chính: ConstraintAuditor, StructuralScorer, Decider, RankingEngine

**Acceptance:** new developer đọc docs là hiểu được flow.

---

## 11. Phần defer (KHÔNG làm trong vòng này)

| Item | Lý do defer |
|---|---|
| L1 Platt scaling / isotonic calibration | Cần ≥500 production query có label. Hiện chỉ có 64 acceptance test. |
| L5 Behavioral feedback loop | Cần analytics events (click, buy, return) — chưa có DB/infra cho events. |
| Gemini reranker cho hard cases | Đo top failure pattern từ production log trước, tránh +500ms latency vô ích. |
| Embedding cache | Optimize sau khi đo latency thực; chưa biết có hit rate đáng kể không. |
| Data quality gate | Catalog WinMart hiện đủ field, gate này là solution chưa có problem. |

---

## 12. Quy tắc giao việc cho agent

Mỗi step (1-11) ở trên là **một đơn vị giao việc độc lập**. Khi giao agent:

1. **Đọc context file:** `PLAN.md` (file này) + các file liên quan trong checklist
2. **Hoàn thành toàn bộ checkbox** của step được giao, không skip
3. **Chạy test** liên quan đến step, đảm bảo pass trước khi báo done
4. **Báo lại:** changed files + acceptance đã đạt + edge case phát hiện được
5. **Không thay đổi** file ngoài scope của step (tránh conflict song song)

### Thứ tự dependency

```
Step 1 (config + tests/) ─→ Step 2 (normalizer) ─→ Step 3 (reindex)
                                                       │
                                                       ▼
                                                  Step 4 (auditor)
                                                       │
                                                       ▼
                                                  Step 5 (scorer)
                                                       │
                                                       ▼
                                                  Step 6 (decider)
                                                       │
                                                       ▼
                                                  Step 7 (engine + xoá scoring.py)
                                                       │
                                                       ▼
                                                  Step 8 (pipeline: alias + telemetry)
                                                       │
                                                       ▼
                                                  Step 9 (querybuilder)
                                                       │
                                                       ▼
                                                  Step 10 (benchmark) ─── Step 11 (docs, song song)
```

**Hoàn toàn tuần tự từ Step 1 → Step 10.** Step 11 (docs) có thể chạy song song với Step 10. Không có step nào khác song song được — vì 4→5→6→7→8 đều dùng output của step trước.

---

## 13. Definition of Done (toàn dự án)

- [ ] Benchmark ≥ 85% trên test_cases.md hiện tại
- [x] Không còn file dead code (reranker.py, scoring.py xoá hết)
- [x] Tất cả magic number về `app/core/config.py`
- [x] `logs/audit.jsonl` có data từ mỗi query
- [ ] Unit test cho normalizer, auditor, scorer, decider — pass 100%
- [x] Doc kiến trúc + ADR đã viết
- [x] `is_exact_request` từ Gemini có ảnh hưởng tới quyết định (verify bằng test case có/không flag)
