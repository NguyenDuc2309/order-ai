# Evaluation Goal — Order-AI

> **Trạng thái:** FROZEN. Tài liệu này là **contract**, không phải checklist.
> Một khi merged, các ngưỡng và quy tắc trong mục 4–7 **không được sửa** để chạy theo
> kết quả benchmark. Nếu cần sửa, đọc mục 9 trước.
>
> **Lý do tồn tại:** Benchmark trước đây là *mục tiêu để tune* — phát hiện case fail
> rồi vá code/prompt cho case đó pass. Đây là **Goodhart's Law**: khi một measure
> trở thành target, nó ngừng là measure tốt. Doc này chuyển từ "đạt X% trên 64 case"
> sang "đạt đồng thời nhiều ràng buộc trực giao trên dev + blind set".

---

## 1. Phạm vi đánh giá

Đo **toàn pipeline** (Extract → Build → Search → Decide) end-to-end qua HTTP API
`/api/v1/search/product`. Không đo từng tầng riêng trong file eval này — unit/integration
test cho từng tầng nằm ở `tests/`.

Đầu ra cần đánh giá:
- `type` ∈ {`exact_match`, `needs_clarification`, `no_result`}
- `items` (0/1/2-3 sản phẩm) với `id`, `name`, `score`
- Các slot do Extract trích (gián tiếp đo qua hành vi pipeline + extraction log)

**Không đánh giá:** latency, cost, infra, UI — thuộc SLO khác.

---

## 2. Triết lý

1. **Đa trục, không có trục thay thế** (chống Goodhart).
   Một hệ thống đạt 100% trên một metric mà thấp trên metric khác = chưa done.
   AND-gate: phải vượt **tất cả** floor trong mục 5, đồng thời.

2. **Capability-based, không chỉ pass-rate** (CheckList; Ribeiro et al., ACL 2020).
   Test phân loại theo *capability* (alias resolution, variant exclusion, abstention…)
   × *test type* (MFT / INV / DIR). Mỗi capability có sàn riêng — không bù trừ.

3. **Blind held-out là nguồn chân lý** (chống test-set overfitting).
   Dev set có thể nhìn, debug, log. **Blind set chỉ chạy khi gate-check**, không bao giờ
   đọc từng case, không tune theo nó. Drift dev → blind > ngưỡng = FAIL ngay cả khi
   dev đạt 100%.

4. **No_result là first-class output, không phải fallback an toàn**.
   Trả `no_result` cho query có sản phẩm trong catalog = FAIL (false abstention).
   Trả items cho query không có trong catalog = FAIL (hallucination).
   Cả hai cân bằng qua precision/recall của abstention (mục 4.D).

5. **Behavioral invariants cứng hơn pass-rate**.
   Một số quy tắc là bất biến hành vi (vd: thêm filler word "cho tôi" không được đổi
   quyết định). Vi phạm = FAIL bất kể % tổng. Xem mục 6.

---

## 3. Phân loại test (taxonomy)

Theo khung **CheckList**: mỗi case có hai trục.

### 3.1 Capability (8 nhóm — khớp G1–G8 hiện tại + behavioral)

| Mã | Capability | Mô tả |
|---|---|---|
| C-ALIAS | Alias / colloquial | "bò húc" → Red Bull, "coke" → Coca |
| C-BRAND | Brand + packaging gate | "coca lon" — brand & uom đều phải đúng |
| C-SPEC | Full specification | brand + size + packaging + qty (qty bị bỏ) |
| C-CAT | Category-only | "nước mắm", "bia lon" — không brand |
| C-VAR | Variant exclusion | "coca thường" → must_not zero/light |
| C-TRAP | Name trap | "trà bí đao coca…" — tên có "coca" nhưng brand=FUZETEA |
| C-ABST | Abstention (no_result) | sản phẩm không có trong catalog |
| C-NL | Natural language / filler | "lấy giúp tôi vài lon pepsi" |

### 3.2 Test type (mỗi capability có ít nhất 1 type của mỗi loại)

| Loại | Mô tả | Ví dụ |
|---|---|---|
| **MFT** (Minimum Functionality) | Case đơn giản, thẳng vào capability | "coca lon" → có coca + lon |
| **INV** (Invariance) | Đổi input theo cách không ảnh hưởng nghĩa, output phải **không đổi** | "coca lon" ↔ "lon coca" ↔ "cho tôi coca lon" — cùng top-1 |
| **DIR** (Directional) | Đổi input theo cách phải đổi output đúng chiều | "coca lon" → "coca chai" đổi packaging trong items |

---

## 4. Metrics (định nghĩa cứng)

Mọi metric tính trên **toàn bộ set** và **per-capability** (stratified).

### A. Decision Type Accuracy
`acc_type = #(predicted_type == expected_type) / N`
Trong đó `expected_type` được ghi cứng cho từng case (không "informational").

### B. Item-level Correctness
Cho case có `expected_type ∈ {exact, clarify}`:
- **Hit@1** = 1 nếu top-1 item match ground-truth (theo `id` hoặc `+term`/`!term` DSL hiện tại, được nâng thành strict).
- **MRR@3** = 1/rank của item đúng đầu tiên trong top-3, 0 nếu không có.
- **Constraint Compliance** = % case mà **mọi** `+term` thỏa và **không** `!term` xuất hiện trong items trả về.

### C. Extraction Slot F1 (gián tiếp đo qua trace log)
Ghi `extraction_log.jsonl` mỗi run. Mỗi case có gold slots `{brand, must_not, size_value, packaging}`.
- `F1_brand`, `F1_must_not`, `F1_size`, `F1_packaging` — micro-F1 từng slot.
- **Joint Slot Exact-Match** = % case mà tất cả 4 slot match đúng (precision/recall đều = 1).

### D. Abstention Precision/Recall (no_result như task riêng)
Đặt `A` = "actual=no_result". `E` = "expected=no_result".
- **Abstention Precision** = P(E | A) = #(A∧E) / #A — *khi nói không có, có đúng là không có không?*
- **Abstention Recall** = P(A | E) = #(A∧E) / #E — *khi không có thật, hệ thống có nhận ra không?*
- **Hallucination Rate** = #(actual có items ∧ expected=no_result) / #E — phải = 0 (zero tolerance, xem 5).
- **False Abstention Rate** = #(actual=no_result ∧ expected≠no_result ∧ in_catalog) / #(expected≠no_result ∧ in_catalog).

> Lưu ý: `in_catalog` là metadata bắt buộc cho mỗi case (`true`/`false`). Hết "no_result là answer hợp lệ cho mọi case" — đó là loophole đã killed.

### E. Behavioral Invariance Pass Rate
% cặp INV test mà output (type + top-1 id) không đổi sau perturbation.
% cặp DIR test mà output đổi đúng chiều quy định.

### F. Confidence Calibration (Brier-style)
Khi `type ∈ {exact, clarify}` và correctness là 0/1:
`Brier = mean((confidence - correct)²)`
Đo xem confidence có dự đoán đúng việc kết quả đúng/sai không.

---

## 5. DONE — Acceptance Gates (AND, frozen)

Hệ thống "done" **khi và chỉ khi** vượt **tất cả** ngưỡng dưới, đồng thời, trên **cả** dev set và blind set, **trong cùng một run**.

### 5.1 Floor overall (dev set)

| Metric | Floor |
|---|---|
| Decision Type Accuracy | **≥ 0.85** |
| Constraint Compliance | **≥ 0.90** |
| MRR@3 (cho case non-abstain) | **≥ 0.80** |
| Joint Slot Exact-Match | **≥ 0.75** |
| Abstention Precision | **≥ 0.95** |
| Abstention Recall | **≥ 0.85** |
| Hallucination Rate | **= 0.00** (zero tolerance) |
| False Abstention Rate | **≤ 0.10** |
| Behavioral Invariance Pass Rate | **≥ 0.95** |
| Brier Score | **≤ 0.20** |

### 5.2 Floor per-capability (dev set)

Mỗi capability C-ALIAS … C-NL phải đạt:
- Type Accuracy **≥ 0.80**, **và**
- Constraint Compliance **≥ 0.85**.

Không có "đổi điểm" — một capability dưới sàn = FAIL toàn bộ, kể cả overall đẹp.

### 5.3 Blind set drift bound

Trên blind set, mỗi metric của 5.1 không được thấp hơn dev set quá **5pp tuyệt đối**.
Vi phạm = FAIL. Đây là kiểm tra overfitting (CapBencher, Chameleon C-BOD pattern).

### 5.4 Zero-tolerance invariants (mục 6 — vi phạm bất kỳ = FAIL)

Liệt kê ở mục 6. Một vi phạm duy nhất trên dev hoặc blind = FAIL.

---

## 6. Behavioral Invariants (zero tolerance)

Đây là quy tắc hành vi, không phải %. Vi phạm **một case** đã FAIL.

| Mã | Bất biến | Nguyên tắc |
|---|---|---|
| INV-1 | Filler word không đổi quyết định: `"X"` và `"cho tôi X"` cho cùng top-1 + cùng type | P7 contract |
| INV-2 | Thứ tự token không đổi quyết định: `"coca lon"` ≡ `"lon coca"` | P2 — name là recall signal |
| INV-3 | Whitespace/dấu thừa không đổi quyết định | robustness |
| DIR-1 | Đổi packaging trong query → items đổi packaging (vd `"coca lon"` → `"coca chai"` không cho ra lon) | P1 — packaging là FACT |
| DIR-2 | Thêm `"thường"` / `"không zero"` → loại variant đó khỏi items | P6 — variant exclusion |
| DIR-3 | Đổi brand → items đổi brand, không leak brand cũ vào top-3 | P1 — brand là FACT |
| ABST-1 | Query out-of-catalog **không bao giờ** trả `exact_match` | P4 — hallucinate = FAIL |
| ABST-2 | Type=`exact_match` chỉ được fire khi audit_fraction ≥ 0.8 **và** items đúng id | P1 — gate cứng |
| EXT-1 | `attributes` không được chứa size word ("nhỏ", "lớn", "vừa") — size word phải vào `size_hint` | PROB-021 |
| EXT-2 | `category` không nằm trong hard_pass (gate brand thôi) | P1 |

---

## 7. Test sets

### 7.1 Dev set (public)

- Vị trí: `scripts/test_cases.md`
- Số case tối thiểu: **80** (hiện 64 — bổ sung 16 case INV/DIR cho mục 6).
- Phân bố: mỗi capability ≥ 8 case, mỗi (capability × test type) ≥ 1.
- Mỗi case có ground truth bắt buộc:
  - `expected_type` (strict, không informational)
  - `in_catalog` (bool)
  - `expected_top1_id` (nullable — bắt buộc cho MFT non-abstain)
  - `+terms`, `!terms` (như hiện tại)
  - `gold_slots` (brand, must_not, size_value, packaging) — null nếu không áp dụng
  - `capability` ∈ {C-ALIAS, …, C-NL}
  - `test_type` ∈ {MFT, INV, DIR}

### 7.2 Blind set (sealed)

- Vị trí: `tests/blind/` — encrypted hoặc `.gitignore` + read-only mount khi chạy gate.
- Số case tối thiểu: **60**, cùng phân bố.
- Quy tắc bất biến:
  - **Không bao giờ** đọc từng case, không log query, không log expected.
  - Runner chỉ output aggregate metrics + per-capability + danh sách **mã case** fail (không nội dung).
  - Soạn bởi người khác / LLM khác / batch khác ngày dev set. Ghi seed + commit hash.
  - Refresh blind set **chỉ khi**: (a) đã đạt all gates, (b) trước khi merge thay đổi lớn pipeline. Không refresh để "thử lại".

### 7.3 Holdout: scaling rule

Khi catalog mở rộng > 5000 SP hoặc thêm vertical mới, blind set phải refresh trước. Đây là điểm duy nhất doc này cho phép "soft change" — vì input domain đã đổi.

---

## 8. Anti-gaming rules

Quy tắc cứng cho cả người lẫn agent (kể cả Claude):

1. **Không sửa test case để pass**. Nếu một case sai về spec, phải sửa kèm rationale + bump version doc này.
2. **Không thêm logic case-specific** (hardcode brand, query string, id) trong code pipeline. Code review reject mọi `if query == "X"`.
3. **Không tune threshold để chạm sàn**. Threshold tune phải có justification từ ablation, không từ "đẩy điểm".
4. **Không re-run nhiều lần lấy run tốt nhất**. Mỗi gate-check chạy với seed cố định, report median của 3 run.
5. **Không xem blind cases khi debug**. Failure log từ blind chỉ trả mã + capability + metric. Người debug đoán nguyên nhân, sửa, chạy lại — không bao giờ thấy query gốc.
6. **Cấm "no_result để an toàn"**. Bất kỳ logic nào trả no_result chỉ vì confidence thấp mà không có justification từ constraint MISMATCH = vi phạm P4.

---

## 9. Amendment process

Tài liệu này là **frozen**. Sửa được, nhưng đắt:

1. PR phải mô tả: nguyên tắc nào (P1–P7 trong `development-plan.md`) hoặc data thực tế nào justify thay đổi.
2. Không sửa ngưỡng (mục 5) vì kết quả benchmark. Sửa ngưỡng vì:
   - Catalog scale thay đổi (vd 1.7k → 50k SP)
   - Định nghĩa task thay đổi (vd thêm multi-item)
   - Phát hiện metric đang đo sai thứ
3. Mỗi amendment ghi vào mục 11 với date + reason.
4. Sửa mục 6 (zero-tolerance invariants) cần thay đổi nguyên tắc gốc — không tự bỏ.

**Không được phép:**
- Hạ floor để "đạt gate".
- Đổi capability một case sang nhóm dễ hơn.
- Thêm "informational" cho metric đang fail.

---

## 10. Cách chạy gate-check

```bash
# 1. Dev set
python scripts/benchmark.py --set dev --seed 42 --runs 3 --report reports/gate/dev.json

# 2. Blind set (giả định runner đã có mode --blind)
python scripts/benchmark.py --set blind --seed 42 --runs 3 --report reports/gate/blind.json

# 3. Gate decision
python scripts/eval_gate.py --dev reports/gate/dev.json --blind reports/gate/blind.json
# Exit 0 = DONE. Exit ≠0 = chưa done, in ra metric/capability nào fail.
```

`eval_gate.py` đọc ngưỡng từ doc này (hard-coded từ mục 5). Sửa code = sửa doc cùng commit.

---

## 11. Amendments

*(chưa có)*

---

## Tham chiếu

- Ribeiro et al., "Beyond Accuracy: Behavioral Testing of NLP Models with CheckList", ACL 2020 — khung MFT/INV/DIR.
- Goodhart's Law / Campbell's Law — chống measure-as-target.
- CapBencher (arXiv 2505.18102), C-BOD (arXiv 2502.07445) — chống test-set overfitting / blind holdout.
- Slot filling F1 contract — CoNLL-2003 NER convention.
- `docs/development-plan.md` — nguyên tắc P1–P7 mà doc này thực thi.
