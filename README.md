# OrderResolve AI

Dịch vụ tìm kiếm sản phẩm thông minh — hybrid ES search (kNN + BM25) + Constraint Audit ranking.

**Latest benchmark:** 52% (33/64) — `reports/benchmark/2026-05-16_15-28-47_score-52pct.json`  
_(Post-reindex target: ≥85%. Xem `reports/CHANGELOG.md` để biết root cause còn lại.)_

## Docs

- [Ranker Architecture](docs/ranker-architecture.md) — pipeline flow, module breakdown, ES schema
- [ADR-001: Constraint Audit](docs/adr-001-constraint-audit.md) — quyết định bỏ legacy scoring
- [Benchmark Changelog](reports/CHANGELOG.md) — lịch sử điểm + phân tích failure

## Hướng dẫn chạy App

### 1. Docker (Khuyên dùng)

```bash
# Khởi chạy Elasticsearch và App
docker compose up --build -d

# Seed dữ liệu (Bắt buộc)
docker compose run --rm app python scripts/seed_data.py
```

### 2. Local

```bash
# Chạy Elasticsearch
docker compose up -d elasticsearch

# Setup venv & cài đặt
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Seed dữ liệu & chạy app
python scripts/seed_data.py
uvicorn main:app --reload --port 8000
```

## Reindex (sau khi thay đổi normalizer hoặc schema)

```bash
# QUAN TRỌNG: chạy thủ công, không chạy trong CI
python scripts/index_products.py
```

`index_products.py` sẽ populate `brand_norm` và `category_norm` — các fields bắt buộc để
`ConstraintAuditor` match đúng. Xem `docs/ranker-architecture.md#es-index-schema` để biết schema đầy đủ.

## Chạy Benchmark

```bash
python scripts/benchmark.py --no-confirm \
  --api-url http://localhost:8001/api/v1/search/product
```

Report JSON + Markdown được lưu vào `reports/benchmark/`. Dashboard HTML: `benchmark_dashboard.html`.
