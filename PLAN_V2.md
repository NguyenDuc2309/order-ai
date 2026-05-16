# Order-AI Plan v2 — Variant Exclusion + Test-case Hygiene + OOC Detection

> Mục tiêu: dứt điểm 3 lớp bug đang gây nhiễu benchmark, không vá lẻ. Tiếp nối PLAN.md
> sau khi đã đạt 80% (51/64).

**Baseline trước rebuild:** 52% — sai logic scoring cũ
**Sau Phase 1-3 (PLAN.md):** 80% (51/64) — pipeline mới + no_result gate sửa
**Target sau plan này:** ≥90% (58/64)

---

## 1. Bug groups còn lại (root cause analysis)

### Group A — Variant hallucination (6 cases, ~9% điểm)

| Case | Query | Excluded leaked |
|---|---|---|
| G3-01 | `2 lon coca` | light, không đường |
| G3-13 | `cho tôi 2 lon coca` | light |
| G6-01 | `coca thường` | light, không đường |
| G6-02 | `2 lon coca bình thường` | light, không đường |
| G6-03 | `pepsi thường` | không calo |
| G6-05 | `bia tiger thường` | crystal |
| G6-04 | `sữa tươi nguyên kem` | tách béo |

**Pattern:** User KHÔNG nhắc variant đặc biệt (hoặc nói "thường/bình thường/nguyên kem" — implicit exclusion) → system trả về variant đặc biệt → đây là hallucination về **specificity**.

**Tại sao xảy ra:**

```
extraction.must_not = []         ← LLM không infer implied exclusion
       │
       ▼
QueryBuilder không có must_not   ← ES không filter variant
       │
       ▼
ES recall trả về cả Light/Zero/không đường
       │
       ▼
StructuralScorer không có signal để penalize variant
       │
       ▼
Decider gate xét hard_pass (brand match) → cả Light và regular đều brand=coca → cùng pass
       │
       ▼
Clarification trả về top-3 diverse → variant lọt vào kết quả
```

**Phân tích nguyên nhân theo layer:**

1. **Layer LLM extraction**: không hiểu "thường" / vắng mặt từ khóa = implied exclusion
2. **Layer ES query**: không có must_not → recall variant
3. **Layer Scorer**: không phân biệt "regular" vs "variant" (cả 2 có brand match)
4. **Layer Decider**: chỉ kiểm hard constraint, không kiểm specificity

→ Fix phải đa tầng, không phải patch 1 chỗ.

---

### Group B — Test case over-specification (2-3 cases)

| Case | Query | Required (sai) | Đúng phải là |
|---|---|---|---|
| G5-05 | `bột giặt` | `+omo` | Bất kỳ bột giặt nào |
| G5-04 | `nước rửa chén` | `+sunlight` | Bất kỳ nước rửa chén |
| G4-05 | `nước mắm` | `+nước_mắm` | Đã ok, category match |
| G4-06 | `snack` | `+snack` | Đã ok, category match |

**Bug:** Test case yêu cầu **brand cụ thể** xuất hiện trong category-only query. Đây là **over-specification** — user chỉ hỏi category, system trả category đúng là OK, ép phải có brand X là sai contract.

**Critical insight từ `critical_issue.md`:** Benchmark phải đo behavior đúng, không phải so expected output tĩnh. Yêu cầu `+omo` cho query `bột giặt` là expected output tĩnh, không đo behavior.

---

### Group C — OOC detection rớt 3 case

| Case | Query | actual | conf |
|---|---|---|---|
| G7-03 | `áo thun nam` | clarify | 0.36 |
| G7-04 | `sữa rửa mặt` | clarify | 0.26 |
| G7-06 | `bia không cồn` | clarify | 0.51 |

**Pattern:** LLM extract được 1 weak constraint (category mơ hồ) → `satisfied_count ≥ 1` → gate `no_result` không fire vì điều kiện hiện tại `satisfied_count == 0`.

Ví dụ "áo thun nam":
- LLM extract: category = "Apparel" hoặc tags=["áo"]
- Catalog không có Apparel → category MISMATCH (satisfied=0)
- Nhưng nếu LLM extract attributes = ["nam"] → match 1 product có tag "nam" → satisfied=1
- Gate không fire → hallucinate

Hoặc "bia không cồn":
- LLM extract category="Beer", attributes=["không cồn"]
- Catalog có Beer → category MATCH (satisfied≥1)
- Gate không fire → trả về bia thường (sai vì user muốn "không cồn")

---

## 2. Giải pháp — Sửa toàn workflow, không patch

### Step 12 — Variant Exclusion: full-stack fix (P0, 4 sub-step)

- [ ] **12.1** **Extraction prompt — implicit exclusion**

  Cập nhật prompt Gemini extractor (`app/services/extractor/gemini_parser.py` hoặc prompt file):

  ```
  Quy tắc must_not:
  1. Nếu user nhắc trực tiếp: "không đường" → must_not = ["không đường"]
  2. Nếu user nói "thường", "bình thường", "regular", "nguyên kem", "nguyên bản" →
     must_not = TẤT CẢ variant đặc biệt của sản phẩm đó:
     - coca/pepsi/nước ngọt + "thường" → must_not = ["light", "zero", "không đường", "diet", "không calo"]
     - sữa + "nguyên kem" → must_not = ["tách béo", "ít béo", "không đường"]
     - bia + "thường" → must_not = ["crystal", "silver", "không cồn", "lite", "light"]
     - nước suối + "thường" → must_not = ["sparkling", "có ga"]
  3. Nếu user KHÔNG nhắc variant gì → must_not = [] (KHÔNG infer thêm)
  ```

  Test với 3 case acceptance: "coca", "coca thường", "coca light" → must_not = [], [light,zero,…], [].

- [ ] **12.2** **QueryBuilder — strict must_not term-keyword filter**

  Hiện `query_builder.py` đã có `must_not_clauses` (multi_match + term tags). Vấn đề: nếu `extraction.must_not` rỗng (LLM không extract) thì ES không filter gì.

  → Phụ thuộc 12.1 — nếu 12.1 đúng thì 12.2 không cần đổi.

  Tuy nhiên thêm 1 layer phòng vệ: **boost negative cho variant keyword trong `name`** dùng `function_score`:

  ```python
  # Nếu user query không có variant keyword → variant trong product là red flag
  variant_keywords = ["light", "zero", "diet", "không đường", "không calo",
                      "tách béo", "ít béo", "crystal", "silver", "sparkling"]
  query_lower = original_query.lower()
  for vk in variant_keywords:
      if vk not in query_lower and vk not in extraction.must_not:
          # User không nói → penalty soft
          should_clauses.append({
              "multi_match": {"query": vk, "fields": ["name"], "boost": -10}
          })
  ```

  (ES không hỗ trợ negative boost trực tiếp trong should — phải dùng `function_score` với `weight: -1`.)

- [ ] **12.3** **StructuralScorer — variant penalty**

  Trong `app/services/ranker/scorer.py`, thêm signal:

  ```python
  VARIANT_TOKENS = {"light", "zero", "diet", "không đường", "không calo",
                    "tách béo", "ít béo", "crystal", "silver",
                    "không cồn", "sparkling"}

  product_name = product.get("name", "").lower()
  query_text = original_query.lower()  # cần truyền từ engine

  if not any(vt in query_text for vt in VARIANT_TOKENS):
      # User không nhắc → product có variant token = penalty
      for vt in VARIANT_TOKENS:
          if vt in product_name:
              structural_score -= config.weight_variant_penalty  # 50
              break  # tránh stack penalty
  ```

  Thêm `weight_variant_penalty: 50` vào `RankerConfig`.

- [ ] **12.4** **Decider — variant guard trong top_3_diverse**

  Trong `_top_3_diverse`, sau khi pick best_seller/largest/smallest, lọc bỏ product có variant token nếu query không nhắc:

  ```python
  def _top_3_diverse(self, rows, extraction):
      if not any(vt in extraction.original_query.lower() for vt in VARIANT_TOKENS):
          rows = [r for r in rows if not self._has_variant_token(r.product)]
      # ... rest of diverse pick
  ```

  Đây là **last line of defense** — phòng khi 12.1-12.3 fail vẫn không leak variant.

**Acceptance Step 12:** G3-01, G3-13, G6-01, G6-02, G6-03, G6-04, G6-05 — 7/7 pass.

---

### Step 13 — Test case hygiene (P1, 1 sub-step)

- [ ] **13.1** Review `scripts/test_cases.md`, áp dụng quy tắc:

  **Quy tắc required keyword (`+term`):**
  - User nói brand cụ thể → `+brand` được dùng (vd "coca cola" → `+coca`)
  - User chỉ nói category → KHÔNG dùng `+brand`. Chỉ dùng `+category-word` nếu cần (vd `+nước_mắm` ok vì "nước mắm" là category word, không phải brand)
  - Colloquial nickname (G5) → mapped brand được nhắc trong test → `+brand` ok (vd `+coca` cho "coke")

  **Sửa cụ thể:**

  | Case | Old | New |
  |---|---|---|
  | G5-04 | `clarify +sunlight` | `clarify` |
  | G5-05 | `clarify +omo` | `clarify` |
  | G4-06 | `clarify +snack` | `clarify` (snack là category word, optional giữ) |
  | G4-05 | `clarify +nước_mắm` | giữ (nước mắm là category word đặc thù) |
  | G4-02 | `clarify +sữa` | giữ (sữa = category) |

**Acceptance:** G5-04, G5-05 đổi từ FAIL → PASS (vì system đang trả đúng category, không phải brand cụ thể).

---

### Step 14 — OOC detection layer 2 (P0, 2 sub-step)

- [ ] **14.1** **Stronger no_result signal — relative gap check**

  Trong `Decider`, ngoài `satisfied_count==0`, thêm điều kiện:

  ```python
  # Nếu top score thấp hơn nhiều so với baseline category — likely OOC
  # Hoặc: nếu top.audit có chỉ 1 weak constraint match (vd chỉ category match,
  # brand specified nhưng MISMATCH) → vẫn là tín hiệu OOC mạnh
  brand_strongly_missed = (
      top.audit.brand == MatchState.MISMATCH
      and top.audit.satisfied_count <= 1  # cho phép 1 weak signal (category)
      and top.structural_score < self.cfg.min_relevance_score * 1.5  # 45
  )
  if brand_strongly_missed:
      return Decision("no_result", confidence=0.85, ...)
  ```

- [ ] **14.2** **must_not violation → no_result khi tất cả top-K vi phạm**

  Cho "bia không cồn" — LLM extract must_not = [] (vì "không cồn" là attribute, không phải variant exclusion). User actually muốn loại bia có alcohol > 0%.

  → Thêm logic: nếu `extraction.attributes` có từ phủ định ("không X", "ít X", "tách X")
  và **không product nào** trong top-K match attribute đó → no_result.

  ```python
  negative_attr_pattern = re.compile(r"^(không|ít|tách|no|low)\s+")
  has_negative_attr = any(negative_attr_pattern.match(a) for a in extraction.attributes)
  if has_negative_attr:
      # Đếm xem có product nào match negative attribute không
      attr_match_count = sum(1 for r in scored_rows[:5] if r.audit.attributes_ratio > 0)
      if attr_match_count == 0:
          return Decision("no_result", confidence=0.80, ...)
  ```

**Acceptance:** G7-03, G7-04, G7-06 — 3/3 pass.

---

### Step 15 — Verify + benchmark (P0)

- [ ] **15.1** Rebuild docker image
- [ ] **15.2** Run full benchmark: `python3 scripts/benchmark.py --no-confirm`
- [ ] **15.3** So với baseline 80% (51/64):
  - Step 12 → +6-7 case (G3-01, G3-13, G6-01..05)
  - Step 13 → +1-2 case (G5-04, G5-05)
  - Step 14 → +3 case (G7-03, G7-04, G7-06)
  - **Expected: 90-94% (58-60/64)**
- [ ] **15.4** Append kết quả vào `reports/CHANGELOG.md`

---

## 3. Định nghĩa hoàn thành

- [ ] Variant exclusion FAIL = 0 (Step 12)
- [ ] Test case không yêu cầu brand cho category-only query (Step 13)
- [ ] no_result fire khi negative-attribute không match catalog (Step 14)
- [ ] Benchmark ≥ 90%
- [ ] Cập nhật `docs/ranker-architecture.md` với variant guard layer (Step 12.3-12.4)
- [ ] ADR-002: "Multi-layer defense against variant hallucination"

---

## 4. Quy tắc giao việc

1. Step 12 PHẢI thực hiện đủ 4 sub-step (12.1 → 12.4), không skip layer nào
2. Step 13 chỉ chạm `test_cases.md` — KHÔNG chạm logic
3. Step 14 chỉ chạm `decider.py` — KHÔNG chạm scorer
4. Step 15 không sửa code, chỉ chạy + ghi report

---

## 5. Tại sao multi-layer (không patch 1 chỗ)?

Theo critical_issue.md: AI pipeline không nên có single point of failure. Variant hallucination
là **systemic bug** xuất hiện qua nhiều layer:

| Layer | Vai trò |
|---|---|
| 12.1 LLM | Hiểu intent đúng — extract must_not đầy đủ |
| 12.2 ES | Filter tại storage — recall không có variant từ đầu |
| 12.3 Scorer | Penalize variant lọt qua filter |
| 12.4 Decider | Last guard — không leak vào response |

Mỗi layer độc lập, mỗi layer fail thì layer sau vẫn catch. Đây là **defense in depth**, không phải over-engineering.

Nếu chỉ fix LLM (12.1): khi LLM API quota hết → fallback fail. Nếu chỉ fix scorer: LLM trả must_not đúng nhưng scorer không biết variant token là gì → vẫn leak.
