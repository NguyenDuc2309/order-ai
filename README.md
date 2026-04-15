# OrderResolve AI Service

Dich vu tim kiem san pham duoc mo-dun hoa theo 3 lop va orchestration bang LangGraph:

- Boc tach thuc the: Gemini (`app/services/extractor/`)
- Truy van hybrid: Elasticsearch (`app/services/search/`)
- Danh gia ket qua 1 hoac 3: Ranker (`app/services/ranker/`)

## Cau truc chinh

- `app/api/v1/search.py`: endpoint `POST /api/v1/search/product`
- `app/core/clients/`: ket noi Gemini va Elasticsearch
- `app/graph/`: pipeline LangGraph (extract -> query -> search -> rerank -> decide)
- `app/prompts/`: prompt template phien ban hoa
- `app/models/`: pydantic schema request/extraction/response
- `scripts/data_enrichment.py`: script lam sach du lieu legacy truoc indexing
- `scripts/seed_data.py`: tao index + seed 50 san pham mock vao Elasticsearch
- `tests/`: unit tests cho extractor/ranker/nodes/graph

## Chay nhanh sau khi pull code

Bat buoc seed DB truoc khi test API, neu khong thi Elasticsearch khong co data de tra ket qua.

### Cach 1: Docker (khuyen nghi)

```bash
# 0) Chinh port app trong .env (tranh xung dot 8000)
# APP_PORT=8010

# 1) Build + start app + Elasticsearch
docker compose up --build -d

# 2) Seed data (bat buoc)
docker compose run --rm app python scripts/seed_data.py

# 3) Theo doi logs pipeline step-by-step
docker compose logs -f app

# 4) Goi test API
curl -X POST http://localhost:${APP_PORT}/api/v1/search/product \
  -H "Content-Type: application/json" \
  -d '{"query":"mua 2 chai coca lon khong lay zero","user_id":"usr_123","context":"supermarket"}'
```

Neu can seed lai tu dau:

```bash
docker compose run --rm app python scripts/seed_data.py
```

### Cach 2: Local (khong Docker)

```bash
# 1) Chay Elasticsearch bang Docker (chi can service ES)
docker compose up -d elasticsearch

# 2) Setup app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 3) Seed data (bat buoc)
python scripts/seed_data.py

# 4) Chay app va xem logs node
uvicorn main:app --reload --port 8000
```

Khi goi API, terminal se in log tung node:

- `extract_node` -> thong tin trich xuat + vector dims
- `build_query_node` -> so luong must/filter/must_not
- `search_node` -> tong hits
- `rerank_node` -> top confidence
- `decide_node` -> status cuoi cung

## Benchmark nhanh 10 prompts

```bash
BENCHMARK_API_URL=http://localhost:${APP_PORT}/api/v1/search/product python scripts/benchmark_prompts.py
```

Ket qua benchmark duoc luu:

- `reports/benchmark_results.csv`
- `reports/benchmark_report.md`

## Test unit

```bash
pytest -q
```
