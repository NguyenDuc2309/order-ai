# OrderResolve AI

Dịch vụ tìm kiếm sản phẩm thông minh.

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

## Chạy Testcase

```bash
API_URL=http://localhost:8000/api/v1/search/product python scripts/testcases.py
```
