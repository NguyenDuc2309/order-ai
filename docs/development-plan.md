# Development Framework & Rules — Order-AI

> **Tài liệu này là gì:** bộ khung neo cho phát triển — gồm mục tiêu, nguyên tắc, kiến trúc,
> data contract và quy tắc phát triển. Nó là **spec đứng yên**, KHÔNG phải refactor checklist.
> Không có "phase 1 làm xong thì tick" — tiến độ và việc cần làm nằm ở `problem-list.md`.
>
> **Cách dùng:** mọi thay đổi code phải trỏ về một nguyên tắc (P-x). Nếu một thay đổi không
> khớp khung → hoặc thay đổi sai, hoặc khung cần sửa có chủ đích (ghi lý do ở mục 6.3).

---

## 1. Mục tiêu & Ranh giới (bất biến)

**Hệ thống làm:**
- Input: một câu tiếng Việt tự nhiên của người mua.
- Output: danh sách sản phẩm xếp hạng + loại quyết định (`exact_match` / `needs_clarification`
  / `no_result`) + `confidence`.
- Nhiệm vụ duy nhất: **hiểu intent + tìm sản phẩm khớp**.

**Hệ thống KHÔNG làm** (thuộc downstream node, có nguồn dữ liệu riêng):
- Số lượng đặt mua. — Tồn kho / còn hàng. — Giá / khuyến mãi. — Giỏ hàng / đơn hàng.

Lý do: dữ liệu trên thay đổi theo từng transaction, không thể đồng bộ với vector store.

---

## 2. Nguyên tắc thiết kế (điểm neo — cite bằng mã P-x)

- **P1 — Decision bám FACT, không bám phán đoán.**
  Field do LLM *suy đoán* không được quyền gate quyết định. Chỉ *fact* — điều người dùng nói
  rõ — mới được gate. Phán đoán mơ hồ chỉ làm soft signal (cộng/trừ điểm nhẹ).

- **P2 — Field cấu trúc của catalog là nguồn chân lý; tên sản phẩm chỉ là tín hiệu recall.**
  Tên sản phẩm retail chứa nhiều dữ liệu nhưng KHÔNG đáng tin:
  - *"Trà bí đao Coca la hán quả"* có chữ "Coca" trong tên nhưng `brand` thật là **FUZETEA**.
  - Sản phẩm retail na ná nhau: cùng tên *"Coca Zero Vanilla 320ml"* có 3 bản chỉ khác `uom`
    (Lon / Gói 6 / Thùng 24). Tên không phân biệt được — chỉ field cấu trúc phân biệt.

  Vì vậy: **audit/matching chính xác phải bám field cấu trúc** (`brand`, `packaging`,
  `category`, `size_value`…). Tên chỉ dùng cho BM25 recall, không dùng làm bằng chứng.
  Field cấu trúc thiếu/sai → sửa ở khâu index từ CSV nguồn, **không phỏng đoán từ tên**.

- **P3 — ES chỉ chứa catalog data (đổi chậm).**
  Operational data (tồn kho, giá, sale, discount) không bao giờ index vào ES.

- **P4 — "Không tìm thấy" là output trung thực và hợp lệ.**
  Thất bại = hallucinate (trả sản phẩm sai). `no_result` khi catalog thực sự không có →
  không tính là lỗi.

- **P5 — Một nguồn chân lý cho taxonomy.**
  Category, packaging, variant vocabulary định nghĩa một chỗ duy nhất. Extraction prompt,
  index mapping, audit cùng tham chiếu. Không có "bản dịch" song song.

- **P6 — Variant exclusion phòng thủ nhiều lớp.**
  Loại trừ variant (zero/light/diet…) đi qua đủ chuỗi: prompt → ES `must_not` filter →
  scorer penalty → decider guard. Một lớp thủng thì lớp sau vẫn chặn.

- **P7 — Mỗi tầng có contract rõ ràng.**
  Tầng sau chỉ phụ thuộc *output contract* của tầng trước, không phụ thuộc nội bộ tầng đó.

---

## 3. Kiến trúc tầng

Pipeline 4 tầng tuần tự.

| Tầng | Input | Output | Trách nhiệm | KHÔNG được làm |
|---|---|---|---|---|
| **Extract** | câu query thô | `ExtractionResult` + query vector | chuẩn hóa query messy thành dữ liệu cấu trúc | đoán số lượng; nhét opinion vào field gate |
| **Build Query** | `ExtractionResult` + vector | ES hybrid query | dựng BM25 + kNN + soft boost + `must_not` filter | hard-filter theo phán đoán mơ hồ |
| **Search** | ES query | ≤20 hit + raw score | thực thi tìm kiếm | logic nghiệp vụ |
| **Decide** | hit list | quyết định + confidence | Audit → Score → Decide | để phán đoán gate (P1); trả quantity/giá |

Tầng Decide gồm 3 layer: **Audit** (đối chiếu constraint → `MatchState`) → **Score** (raw score
+ điều chỉnh theo audit) → **Decide** (chọn loại quyết định + confidence).

---

## 4. Data Contract

> Đổi contract = sửa mục này trong cùng commit, ghi lý do ở 6.3.

### 4.1 ExtractionResult — phân loại field theo P1

| Field | Loại | Được gate? | Ghi chú |
|---|---|---|---|
| `product_name` | phái sinh (chuẩn hóa query) | Không | input BM25 |
| `brand` | FACT (user nói tên brand) | Có — chỉ MISMATCH mới loại | tín hiệu phân biệt mạnh nhất |
| `must_not` | FACT (phủ định / "thường") | Có — dùng làm filter | xương sống P6 |
| `size_value` + `size_unit` | FACT (user nói số) | Soft | chỉ set khi có số |
| `unit_raw` | FACT (đóng gói user nói) | Soft boost | tập đóng |
| `attributes` | nửa fact nửa đoán | Soft scoring | không gate |
| `category` | SUY ĐOÁN (LLM infer) | **Không gate** — soft boost | không nằm trong `hard_pass` |
| `size_hint` | chỉ hợp lệ khi phái sinh từ `size_value` | Soft | không nhận LLM tự đoán "lớn/nhỏ" |

Field `is_exact_request` **không tồn tại** trong contract. Mức độ cụ thể của yêu cầu do
decider tự suy xác định: `is_specific = bool(brand) or bool(unit_raw) or bool(size_value)`.

### 4.2 ES Document — chỉ catalog data (P3)
- Text cho BM25: tên đầy đủ, tên gốc, brand hiển thị.
- Keyword cho filter/boost: `brand_norm`, `category_norm`, `packaging`.
- Số cho so sánh size: `size_value`, `size_value_ml`.
- Vector 768 chiều cho kNN.
- **Cấm:** `available_quantity`, `sale_price`, `discount_rate`, `is_best_seller`.

### 4.3 Nguồn dữ liệu catalog — `data/winmart_products.csv` (2774 sản phẩm)
Đây là **chuẩn**. Khi index, lấy truth từ field cấu trúc, không từ tên:
- `brand` → `brand_norm`. (Field `brand` đáng tin; tên thì không.)
- `mch1`–`mch5` → `category_norm`. (`source_category_name` là **rác** — "Bông tắm" bị gán
  category "Sữa các loại"; không bao giờ dùng `source_category_name`.)
- `uom` → `packaging`. (Phân biệt Lon / Chai / Thùng / Gói khi tên không phân biệt được.)
- Size lấy từ tên chỉ khi không có field cấu trúc, và phải parse có kiểm chứng.

### 4.4 SearchResponse
- `type`, `confidence`, `items` (mỗi item: `id`, `name`, `score`), `message`.
- **Cấm:** trường `quantity` trên item.

---

## 5. Phân biệt FACT vs SUY ĐOÁN (tham chiếu cho P1)

- **FACT** = điều người dùng nói rõ, trích từ text mà không cần suy luận.
  Ví dụ: "coca" → brand; "không lấy zero" → must_not; "chai 1.5 lít" → size.
- **SUY ĐOÁN** = điều LLM phải suy luận thêm, có thể sai.
  Ví dụ: category của "bò húc"; "lớn/nhỏ" là bao nhiêu ml; user "có vẻ" muốn gì.
- **Quy tắc:** FACT được gate. SUY ĐOÁN chỉ làm soft signal. Không ngoại lệ ngầm.

---

## 6. Quy tắc phát triển

### 6.1 Bám dữ liệu thật, không phỏng đoán
Trước khi viết logic xử lý một field, **phải xem dữ liệu thật** của field đó trong CSV/ES.
Không viết logic dựa trên giả định về hình dạng dữ liệu.
> Bài học: bug SIZE_HINTS chết hoàn toàn vì code viết theo giả định về `category_norm`
> ("beverage_can"…) trong khi dữ liệu thật là "soft drink"… — không khớp, không ai phát hiện.

### 6.2 Cite nguyên tắc khi thay đổi
Mỗi commit/PR mô tả: phục vụ **P-x** nào. Thay đổi không cite được nguyên tắc nào → xem lại.

### 6.3 Sửa khung có chủ đích
Đổi data contract (mục 4) hoặc nguyên tắc (mục 2) phải ghi amendment vào đây kèm lý do:
- *(chưa có amendment)*

### 6.4 Không vá tạm
Khi một fix mâu thuẫn khung: dừng, đối chiếu khung, sửa toàn luồng — không patch 1-2 file
rồi để lại chỗ mâu thuẫn. Vấn đề ngoài scope hiện tại → ghi `problem-list.md`.

---

*Tạo: 2026-05-21. Việc cần làm và mức ưu tiên: xem `docs/problem-list.md`.*
