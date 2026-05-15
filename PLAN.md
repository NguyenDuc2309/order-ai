# Implementation Plan — order-resolve-ai

> Thực thi từng Step, đợi review xong mới đi tiếp.  
> Mỗi Step có checklist rõ ràng. Không code bước sau khi bước trước chưa được approve.

---

## Step 0 — Scan & Audit (DONE — chỉ đọc, không sửa)

### Phát hiện vấn đề

| # | File | Vấn đề | Mức độ |
|---|------|---------|--------|
| 1 | `scripts/seed_data.py` | Thiếu field `base_name`, `brand_display`, `mch_path` — BM25 query builder search trên các field này (boost 4, 3, 2) nhưng document không có → search mù | CRITICAL |
| 2 | `scripts/seed_data.py` | Thiếu field `is_best_seller` — engine._top_three_diverse dùng `r["product"]["is_best_seller"]` → KeyError | CRITICAL |
| 3 | `scripts/seed_data.py` | `tags` chứa empty string (`""` khi tag rỗng) → noise trong filter | BUG |
| 4 | `scripts/seed_data.py` | `embed_text` = normalized text mất dấu, thiếu brand/category context → vector search kém | QUALITY |
| 5 | `scripts/seed_data.py` | Category lowercase ("soft drink") thay vì title case ("Soft Drink") — Gemini trả về title case → scoring so sánh `.lower()` nên pass nhưng inconsistent | MINOR |
| 6 | `scripts/seed_data.py` | Mapping thiếu các field mới → ES không index đúng | CRITICAL |
| 7 | `app/services/ranker/engine.py` | Line 111: `r["product"]["is_best_seller"]` → KeyError nếu field vắng mặt | BUG |
| 8 | `scripts/testcases.py` | Chỉ có 5 test case, không có ground truth, không có pass/fail | MISSING |
| 9 | `scripts/benchmark.py` | Chưa tồn tại | MISSING |

### Confidence Formula (đã review — hợp lệ, không random)

```
gap       = top1_score − top2_score
base_conf = sigmoid(gap / 10)          ∈ (0.5, 1.0)

Bands:
  all_constraints_matched AND top_score > 100 → confidence = 0.95 + 0.04 × base_conf  ∈ [0.97, 0.99]
  all_constraints_matched                     → confidence = 0.85 + 0.10 × base_conf  ∈ [0.90, 0.95]
  constraints NOT matched                     → confidence = base_conf × 0.70          ∈ (0.35, 0.70)

exact_match khi: confidence ≥ 0.85 AND gap > 20 (matched) hoặc > 40 (unmatched) AND all_matched
```

Công thức này DETERMINISTIC — không random. Cần thêm comment giải thích vào code.

---

## Step 1 — Fix Insert Pipeline (seed_data.py + engine.py bug)

> **Mục tiêu**: Đảm bảo data insert vào ES đúng schema mà pipeline đang kỳ vọng.

### Checklist Step 1

- [x] **1.1** `seed_data.py`: thêm field `base_name` = tên thương hiệu (e.g. "Coca Cola")
- [x] **1.2** `seed_data.py`: thêm field `brand_display` = tên thương hiệu title case (text field để BM25 search)
- [x] **1.3** `seed_data.py`: thêm field `mch_path` = category path đơn giản (e.g. "Soft Drink")
- [x] **1.4** `seed_data.py`: thêm field `is_best_seller = False` (default)
- [x] **1.5** `seed_data.py`: rename `pack_size` → `pack_count` cho nhất quán với crawl script
- [x] **1.6** `seed_data.py`: fix `tags` — filter empty string
- [x] **1.7** `seed_data.py`: cập nhật `embed_text` = `"{name} {brand_display} {category}"` (rich text)
- [x] **1.8** `seed_data.py`: cập nhật `build_index_mapping()` thêm các field mới đúng type
- [x] **1.9** `seed_data.py`: category sang title case cho consistent ("Soft Drink" thay vì "soft drink")
- [x] **1.10** `engine.py`: line 111 fix `["is_best_seller"]` → `.get("is_best_seller", False)`
- [x] **1.11** `engine.py`: thêm comment giải thích confidence formula rõ ràng

**Files sửa**: `scripts/seed_data.py`, `app/services/ranker/engine.py`  
**Không đụng**: crawl script, API, Docker

---

## Step 2 — Crawl Data & Verify Insert (smoke test nhỏ)

> **Mục tiêu**: Chạy seed hoặc crawl một lượng nhỏ data, kiểm tra ES document có đúng schema chưa trước khi chạy full.

### Checklist Step 2

- [x] **2.1** Chạy `seed_data.py` → index ~200 synthetic products
- [x] **2.2** Kiểm tra ES: query 3 document ngẫu nhiên, verify có đủ field (`base_name`, `brand_display`, `mch_path`, `is_best_seller`, `name_vector`)
- [x] **2.3** Gọi API thủ công 3 query đơn giản, kiểm tra response hợp lý (không crash, có items)
- [ ] **2.4** (Optional) Nếu muốn real data: `crawl_winmart_products.py --pages-per-keyword 1 --max-categories 5 --index-es`

**Không chạy benchmark cho đến khi Step 2 pass hết.**

---

## Step 3 — Build Benchmark Script (benchmark.py)

> **Mục tiêu**: 50 test case có ground truth, chạy precheck 5 case trước, lưu report timestamp.

### Thiết kế

**50 Test Cases phân bố:**

| Group | Type | # Cases | Mô tả |
|-------|------|---------|-------|
| G1 | Brand-only | 10 | "coca cola", "heineken" → needs_clarification (nhiều size) |
| G2 | Brand + Packaging | 5 | "coca lon", "pepsi chai" → needs_clarification (size mơ hồ) |
| G3 | Brand + Size | 7 | "coca 330ml", "vinamilk 1l" → needs_clarification (nhiều tag variant) |
| G4 | Category-only | 7 | "bia", "sữa tươi", "nước ngọt" → needs_clarification |
| G5 | Size hint | 4 | "chai lớn", "lon nhỏ" → needs_clarification |
| G6 | Synonyms / Colloquial | 6 | "bò húc", "mì tôm", "coke" → needs_clarification |
| G7 | Quantity | 4 | "3 lon bia tiger" → needs_clarification |
| G8 | Attributes | 3 | "ít đường", "không cồn" → needs_clarification / no_result |
| G9 | No-result | 4 | "iphone", "vitamin C" → no_result |
| **Total** | | **50** | |

**Pass/Fail criteria (mỗi case):**
```
PASS  = response.type == expected_type
INFO  = brand_hit: expected_brand xuất hiện trong top items (không ảnh hưởng PASS/FAIL)

Score = PASS_count / 50 × 100%
```

**Precheck flow:**
```
1. Chạy 5 case đầu
2. In kết quả, hỏi "Continue? [y/N]"
3. Nếu N → dừng, không lưu report đầy đủ
4. Nếu Y → chạy tiếp 45 case còn lại
5. Lưu report
```

**Report format:**
```
reports/
  benchmark/
    2026-05-15_14-30-00_score-72pct.json   ← machine-readable
    2026-05-15_14-30-00_score-72pct.md     ← human-readable
    history.json                            ← append mỗi lần chạy, dùng cho tracking
```

**Checklist Step 3:**
- [x] **3.1** Viết 50 test case với `id`, `query`, `expected_type`, `expected_brands`, `desc`
- [x] **3.2** Implement `precheck()` — chạy 5 case, prompt confirm
- [x] **3.3** Implement `run_all()` — chạy 50 case với progress bar text
- [x] **3.4** Implement `score_case()` — PASS/FAIL logic rõ ràng
- [x] **3.5** Implement `save_report()` — JSON + MD với timestamp
- [x] **3.6** Implement `append_history()` — ghi vào `history.json` (date, score%, pass, fail, run_id)
- [x] **3.7** CLI args: `--precheck-only`, `--no-confirm`, `--api-url`, `--output-dir`

---

## Step 4 — HTML Dashboard (benchmark_dashboard.html)

> **Mục tiêu**: Visualize history.json + latest report trong browser. Tự tracking được qua ngày.

### Thiết kế Dashboard

**Tính năng:**
1. **Timeline chart** — Score% theo ngày (Line chart dùng Chart.js CDN, không cần server)
2. **Latest run summary** — Pass/Fail, avg latency, breakdown theo group
3. **Test case table** — Filter by group / PASS/FAIL / type, click để xem detail
4. **Load từ file local** — `<input type="file">` để load `history.json` + latest report JSON (không cần server, chạy `file://` được)
5. **Auto-refresh** — Nếu mở từ server, poll mỗi 30s (optional)

**Stack**: Pure HTML + Chart.js CDN + Vanilla JS (zero dependencies, mở file:// hoặc serve tĩnh)

**Checklist Step 4:**
- [x] **4.1** Layout: header + 3 panels (summary, timeline, table)
- [x] **4.2** Timeline chart dùng Chart.js
- [x] **4.3** Test case table với filter (All/Pass/Fail/G1-G9/Search)
- [x] **4.4** Load JSON từ file input (history.json + report JSON)
- [x] **4.5** Group breakdown bar chart
- [x] **4.6** Badge màu PASS/FAIL/type per row

**File**: `scripts/benchmark_dashboard.html`

---

## Step 5 — Docker Verify

> **Mục tiêu**: Đảm bảo `docker-compose up` chạy được, app healthy, crawl script chạy được trong container context.

### Checklist Step 5

- [x] **5.1** Review Dockerfile — đủ deps, port đúng, thêm `PYTHONUNBUFFERED=1`
- [x] **5.2** Review docker-compose.yml — healthcheck ✓, env_file ✓, APP_PORT substitution ✓
- [x] **5.3** Update `.dockerignore` — thêm `.git`, `.claude`, `reports/`, `*.md`
- [x] **5.4** Document lệnh seed/crawl từ host

### Quick Start Commands

```bash
# 1. Build + start ES + app
docker-compose up -d --build

# 2. Seed synthetic data (chạy từ host, ES exposed port 9200)
ELASTIC_URL=http://localhost:9200 python scripts/seed_data.py

# 3. (Optional) Crawl WinMart thật, 5 categories, 2 pages/keyword
python scripts/crawl_winmart_products.py \
  --output /tmp/winmart.csv \
  --pages-per-keyword 2 --max-categories 5 \
  --index-es

# 4. Precheck 5 cases trước
python scripts/benchmark.py --api-url http://localhost:8000/api/v1/search/product --precheck-only

# 5. Full benchmark 50 cases (sau khi precheck ok)
python scripts/benchmark.py --api-url http://localhost:8000/api/v1/search/product --no-confirm

# 6. Xem dashboard (mở trực tiếp trong browser)
open scripts/benchmark_dashboard.html
# Hoặc serve tĩnh:
python -m http.server 3000   # rồi vào http://localhost:3000/scripts/benchmark_dashboard.html
```

---

## Thứ tự thực thi

```
Step 1 → Step 2 → Step 3 → Step 4 → Step 5  [ALL DONE]
```

---

## Current Status

| Step | Status |
|------|--------|
| Step 0 — Scan & Audit | ✅ Done |
| Step 1 — Fix Insert Pipeline | ✅ Done |
| Step 2 — Crawl & Verify | ✅ Done |
| Step 3 — Benchmark Script | ✅ Done |
| Step 4 — HTML Dashboard | ✅ Done |
| Step 5 — Docker Verify | ✅ Done |
