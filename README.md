# OrderResolve AI

Dịch vụ tìm kiếm sản phẩm thông minh — hybrid ES search (kNN + BM25) + Constraint Audit ranking.

Pipeline 4 tầng: **Extract** (Gemini LLM + Embedding) → **Build Query** (hybrid ES) →
**Search** (kNN + BM25) → **Decide** (Audit → Score → Decide).

## Docs

- [System Design](docs/system-design.md) — pipeline flow, module breakdown, ES schema
- [Eval Goal](docs/eval-goal.md) — **frozen** acceptance criteria (không sửa để pass)
- [ADR-001: Constraint Audit](docs/adr-001-constraint-audit.md) — quyết định bỏ legacy scoring
- [Problem List](docs/problem-list.md) — backlog và root cause

---

## Chạy App

### Docker (Khuyên dùng)

```bash
docker compose up --build -d
docker compose run --rm app python scripts/seed_data.py
```

### Local

```bash
docker compose up -d elasticsearch
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/seed_data.py
uvicorn main:app --reload --port 8000
```

### Reindex (sau khi thay đổi normalizer hoặc schema)

```bash
# Chạy thủ công, không chạy trong CI
python scripts/index_products.py
```

---

## Chạy Benchmark (dev set)

```bash
python scripts/benchmark.py --no-confirm \
  --api-url http://localhost:9199/api/v1/search/product \
  --output-dir reports/gate
```

Report JSON + Markdown lưu vào `reports/gate/`. Dashboard HTML: `benchmark_dashboard.html`.

---

## Đánh giá chất lượng — Eval Gate

### Quy trình chuẩn (mỗi khi muốn kiểm tra "done chưa")

```bash
# Bước 1 — Chạy benchmark để lấy results JSON
python scripts/benchmark.py --no-confirm \
  --api-url http://localhost:9199/api/v1/search/product \
  --output-dir reports/gate

# Bước 2 — Chạy gate-check trên dev set
python scripts/eval_gate.py \
  --dev reports/gate/<timestamp>_score-XXpct.json

# Bước 3 (optional) — Chạy INV pairs live để đo behavioral invariance
python scripts/eval_gate.py \
  --dev reports/gate/<timestamp>_score-XXpct.json \
  --api-url http://localhost:9199/api/v1/search/product
```

Exit code: **0 = DONE** (all gates passed), **1 = FAIL** (in ra metric nào fail).

### Khi đã chạy xong dev, chạy gate-check blind set

> **Quy tắc niêm phong:** không đọc từng case trong `tests/blind/blind_set.jsonl` khi debug.
> Runner chỉ trả aggregate metrics + capability breakdown, không expose query cụ thể.

```bash
# Bước 1 — Chạy benchmark với blind set (cần script adapter — xem bên dưới)
python scripts/benchmark_blind.py --no-confirm \
  --api-url http://localhost:9199/api/v1/search/product \
  --blind-set tests/blind/blind_set.jsonl \
  --output-dir reports/gate

# Bước 2 — Gate-check kết hợp dev + blind (drift check)
python scripts/eval_gate.py \
  --dev   reports/gate/dev_<timestamp>.json \
  --blind reports/gate/blind_<timestamp>.json
```

> `benchmark_blind.py` — xem #TODO bên dưới. Hiện tại có thể dùng `--blind-jsonl` trực tiếp
> khi blind JSONL đã được annotate `actual_type` + `top_items` từ API.

### Gate tóm tắt (floors từ eval-goal.md §5.1)

| Metric | Floor | Chiều |
|---|---|---|
| Decision Type Accuracy | ≥ 0.85 | ↑ |
| Constraint Compliance | ≥ 0.90 | ↑ |
| MRR@3 | ≥ 0.80 | ↑ |
| Abstention Precision | ≥ 0.95 | ↑ |
| Abstention Recall | ≥ 0.85 | ↑ |
| Hallucination Rate | = 0.00 | ↓ (zero tolerance) |
| False Abstention Rate | ≤ 0.10 | ↓ |
| Behavioral Invariance | ≥ 0.95 | ↑ |
| Brier Score | ≤ 0.20 | ↓ |

Phải vượt **tất cả** floors đồng thời. Không có bù trừ.
Mỗi capability (C-ALIAS … C-NL) phải đạt Type Accuracy ≥ 0.80 và Constraint Compliance ≥ 0.85 riêng.
Drift dev → blind > 5pp trên bất kỳ metric nào = FAIL.

### Anti-gaming — đọc trước khi sửa code

> Xem [docs/eval-goal.md §8](docs/eval-goal.md) để hiểu đầy đủ. Tóm lại:
> - **Không sửa test case để pass.** Không thêm logic case-specific trong pipeline.
> - **Không tune threshold để chạm sàn** mà không có ablation justification.
> - **Không re-run nhiều lần lấy run tốt nhất.** Mỗi gate-check = 1 run với seed cố định.
> - **Không xem blind cases khi debug.** Failure log blind chỉ trả mã + capability + metric.

---

## Test Sets

| Set | Vị trí | Cases | Mục đích |
|---|---|---|---|
| Dev | `scripts/test_cases.md` | 73 | Debug, profile, tune — nhìn được |
| Blind | `tests/blind/blind_set.jsonl` | 60 | Gate-check overfitting — không đọc từng case |

Dev: 54 MFT + 9 INV + 9 DIR, phân theo 8 capability.
Blind: 40 MFT + 10 INV + 10 DIR, sinh bởi LLM độc lập, phân theo 8 capability.

---

## Trạng thái hiện tại

**Gate-check lần cuối (2026-06-08):** 8/9 metric FAIL trên dev.

```
Decision Type Accuracy  0.094   (floor ≥0.85)  ✗
Constraint Compliance   1.000   (floor ≥0.90)  ✓
MRR@3                   0.812   (floor ≥0.80)  ✓
Abstention Precision    0.357   (floor ≥0.95)  ✗
Abstention Recall       1.000   (floor ≥0.85)  ✓
Hallucination Rate      0.000   (floor =0.00)  ✓
False Abstention Rate   0.188   (floor ≤0.10)  ✗
Behavioral Invariance   NOT_MEASURED
Brier Score             0.064   (floor ≤0.20)  ✓
```

Root cause chính: false abstention — hệ thống trả `no_result` cho sản phẩm có thật trong catalog
(PROB-021). Benchmark cũ ghi 100% vì coi mọi `no_result` đều hợp lệ — đó là sai. Xem
[docs/problem-list.md](docs/problem-list.md) để biết danh sách fix.
