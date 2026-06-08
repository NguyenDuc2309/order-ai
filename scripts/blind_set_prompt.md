# Prompt — sinh Blind Test Set cho Order-AI

> Dán toàn bộ phần dưới đây vào LLM (Gemini 2.5 Pro / GPT-5 / Claude khác — **không phải
> Claude đang chạy Order-AI codebase**). Yêu cầu output JSONL, không giải thích.

---

## Vai trò

Bạn là kỹ sư QA soạn **blind test set** cho một hệ thống tìm kiếm sản phẩm tiếng Việt.
Test set này sẽ bị **niêm phong** — đội phát triển không bao giờ đọc từng case. Mục đích:
đo overfitting bằng cách so sánh với dev set công khai.

## Hệ thống được test

- **Input:** một câu tiếng Việt tự nhiên (vd `"2 lon coca"`, `"bia heineken thùng"`).
- **Output:** `type` ∈ {`exact_match`, `needs_clarification`, `no_result`} + danh sách items (0/1/3 sản phẩm).
- **Domain:** catalog Winmart ~2700 sản phẩm tiêu dùng — nước giải khát (Coca, Pepsi, Heineken,
  Tiger, Red Bull, Sting, Monster, 333, Saigon, Lavie), sữa (Vinamilk, TH, Ensure), mì gói
  (Hảo Hảo, Omachi, Koreno), snack (Oishi), gia vị (nước mắm, tương ớt), bia, trà (Fuzetea, 0 Độ).
- **Nguyên tắc:**
  - `no_result` = trung thực nói "không có" khi sản phẩm thật sự không có trong catalog (gồm cả variant
    không tồn tại như "bia không cồn", "lavie có ga").
  - Trả items sai khi nên `no_result` = hallucination = FAIL.
  - Trả `no_result` khi sản phẩm có trong catalog = false abstention = FAIL.

## Capability cần phủ (8 nhóm)

| Mã | Mô tả | Ví dụ dev set |
|---|---|---|
| C-ALIAS | Tiếng lóng / nickname tiếng Anh / brand-là-số | "bò húc" (Red Bull), "coke" (Coca), "333" |
| C-BRAND | Brand + packaging rõ | "coca lon", "heineken thùng", "tiger lon" |
| C-SPEC | Full spec (brand + size/packaging + qty bị bỏ) | "2 lon coca", "heineken lon 330ml" |
| C-CAT | Category-only (không brand) | "nước mắm", "bia lon", "snack" |
| C-VAR | Variant exclusion (must_not) | "coca thường" (≠ zero/light), "tiger thường" (≠ silver) |
| C-TRAP | Tên có brand khác nhưng brand thật khác | "trà bí đao coca la hán quả" — brand là FUZETEA |
| C-ABST | Out-of-catalog → no_result | "bia không cồn", "thuốc cảm", "lavie có ga" |
| C-NL | Câu tự nhiên có filler / phrasing dài | "lấy giúp tôi 1 thùng heineken" |

## Test type (theo CheckList)

- **MFT** — Minimum Functionality: một query đơn, đo capability cơ bản.
- **INV** — Invariance: **cặp** (Query A, Query B) khác bề mặt nhưng cùng nghĩa → output phải
  giống hệt (`type` + top-1 id).
- **DIR** — Directional: cặp (A → B) với perturbation có hướng → output phải đổi đúng chiều
  (vd đổi packaging trong query → items đổi packaging).

## Yêu cầu định lượng

- **Tổng:** đúng **60 case**.
- **Phân bố:** mỗi capability **≥ 6 case**; mỗi (capability × test type) **≥ 1**.
- **Tỉ lệ type gợi ý:** ≈ 40 MFT + 10 INV + 10 DIR.
- Tỉ lệ expected: ≈ 50% `clarify`, 25% `exact`, 25% `no_result`.

## Quy tắc tránh leak / overfitting

1. **Không sao chép** bất kỳ query nào từ dev set (đã liệt kê trong "Capability cần phủ" cột ví dụ).
   Phải sáng tạo query mới về **mặt từ vựng**, không chỉ đổi 1 từ.
2. Giữ **cùng phân bố ngữ pháp** (50% câu lệnh ngắn `<5 token`, 30% có filler `<10 token`, 20% dài).
3. Dùng các brand/sản phẩm cùng pool đã liệt kê — không bịa brand không có thật trong domain
   tiêu dùng Việt Nam.
4. Cho C-ABST: query phải là sản phẩm/variant **thật sự không có** trong siêu thị Winmart Việt Nam
   (vd bia không cồn dưới 0.5%, dược phẩm kê đơn, mỹ phẩm cao cấp, đồ điện tử). Không gồm
   "sản phẩm hư cấu" kiểu "Coca màu tím".
5. Cho INV/DIR: cặp (A,B) phải có lý do invariance/directional **rõ ràng**, không mơ hồ.
6. Tiếng Việt phải **tự nhiên**, có dấu đầy đủ, kiểu nói của người mua hàng siêu thị.

## Output format — JSONL (mỗi dòng 1 case, không markdown, không giải thích)

### Schema cho MFT

```json
{"id": "B-MFT-001", "kind": "MFT", "cap": "C-BRAND", "query": "...", "expected_type": "clarify", "in_catalog": true, "required_terms": ["coca","lon"], "excluded_terms": [], "gold_slots": {"brand":"coca_cola","uom":"lon","size_value":null,"size_hint":null,"must_not":[],"category":null}, "rationale": "ngắn gọn 1 câu"}
```

### Schema cho INV

```json
{"id": "B-INV-001", "kind": "INV", "cap": "C-NL", "query_a": "...", "query_b": "...", "invariant": "same_type_and_top1", "anchor_expected_type": "clarify", "rationale": "..."}
```

`invariant` ∈ {`same_type`, `same_top1`, `same_type_and_top1`}.

### Schema cho DIR

```json
{"id": "B-DIR-001", "kind": "DIR", "cap": "C-VAR", "query_a": "...", "query_b": "...", "directional_rule": "items_b_must_exclude:zero,light,không_đường", "rationale": "..."}
```

`directional_rule` là chuỗi mô tả ràng buộc tự nhiên, **một trong** các pattern:
- `items_b_must_contain:<csv_terms>`
- `items_b_must_exclude:<csv_terms>`
- `items_b_packaging_changes_to:<uom>`
- `items_b_brand_changes_to:<brand>`
- `items_b_size_value_approx:<ml>`
- `type_b_must_be:<no_result|exact_match|needs_clarification>`

## Ràng buộc field

- `id` format `B-<KIND>-<NNN>`, NNN bắt đầu từ 001 cho mỗi kind.
- `cap` ∈ {`C-ALIAS`, `C-BRAND`, `C-SPEC`, `C-CAT`, `C-VAR`, `C-TRAP`, `C-ABST`, `C-NL`}.
- `expected_type` ∈ {`exact`, `clarify`, `no_result`} — dùng đúng 3 string này, không variant.
- `in_catalog` = `false` chỉ khi capability là C-ABST hoặc query rõ ràng OOC.
- `required_terms` / `excluded_terms` là array string lowercase, không dấu nháy (vd `["coca","lon"]`).
- `gold_slots.must_not` là array; null nếu user không phủ định.
- `rationale` ≤ 20 từ tiếng Việt.

## Output rules

1. **Chỉ in JSONL** — mỗi dòng một JSON object hợp lệ, không có comment, không markdown wrapper,
   không text giải thích trước/sau.
2. **Đúng 60 dòng**.
3. Mỗi dòng phải parse được bằng `json.loads()` Python độc lập.
4. Thứ tự: gom MFT trước, INV giữa, DIR cuối.
5. Không trùng `id`, không trùng `query` (MFT) hoặc `(query_a, query_b)` (INV/DIR).

## Self-check trước khi xuất

- [ ] 60 dòng, mỗi dòng JSON hợp lệ?
- [ ] Mỗi capability ≥ 6 case (đếm cả INV/DIR pair là 1)?
- [ ] Mỗi (capability × kind) ≥ 1?
- [ ] Không query nào trùng ví dụ dev set ở phần "Capability cần phủ"?
- [ ] Tất cả brand/sản phẩm có thật trong siêu thị tiêu dùng Việt Nam?
- [ ] `in_catalog=false` ⇒ `expected_type` = `no_result`?

Bắt đầu xuất 60 dòng JSONL.
