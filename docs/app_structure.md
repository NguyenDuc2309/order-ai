# OrderResolve AI - Cấu trúc Logic Hệ thống

Tài liệu này chi tiết hóa cấu trúc logic của project OrderResolve AI, tập trung vào luồng xử lý AI, Search và Decision Making để phục vụ việc review code và tối ưu hóa.

## 1. Kiến trúc Tổng quan (Orchestration Layer)
Hệ thống sử dụng **LangGraph** để điều phối các bước xử lý dưới dạng một Directed Acyclic Graph (DAG).

### `app/graph/state.py`
- **Logic:** Định nghĩa "SearchState" - bộ nhớ dùng chung xuyên suốt pipeline.
- **Dữ liệu:** Lưu trữ query gốc, kết quả bóc tách (extraction), vector tìm kiếm, danh sách kết quả từ ES (hits), và kết quả trả về cuối cùng (response).

### `app/graph/pipeline.py`
- **Logic:** Xây dựng khung xương của graph.
- **Luồng đi:** `START` -> `extract_node` -> `build_query_node` -> `search_node` -> `decide_node` -> `END`.
- **Conditional Edges:** Sau `decide_node`, hệ thống sẽ rẽ nhánh dựa trên `type` của response (nếu là `exact_match` thì hoàn tất, nếu không thì đưa ra gợi ý làm rõ).

### `app/graph/nodes.py`
- **Logic:** Wrapper gọi đến các service chuyên biệt.
- **Tối ưu:** Node `extract_node` sử dụng `ThreadPoolExecutor` để chạy song song việc bóc tách thực thể (LLM) và tạo vector embedding (Gemini API) nhằm giảm latency.

---

## 2. Lớp Bóc tách Thông tin (Extraction Layer)

### `app/services/extractor/gemini_parser.py`
- **Logic:** Sử dụng Gemini Flash để parse ngôn ngữ tự nhiên thành cấu trúc JSON dựa trên Pydantic Model.
- **Xử lý lỗi:** Có cơ chế `_fallback_extract` để trả về kết quả mặc định nếu LLM gặp lỗi format, đảm bảo pipeline không bị ngắt quãng (500 error).
- **Tiền xử lý:** Tích hợp `normalize_text` để làm sạch query trước khi đưa vào LLM.

### `app/prompts/extraction_v1.yaml`
- **Logic:** Chứa System Prompt chi tiết cho việc bóc tách. 
- **Quy tắc:** Định nghĩa cách nhận diện Brand, Category, Size (Volume), Attributes, và các từ khóa phủ định (must_not).

---

## 3. Lớp Tìm kiếm (Search Layer)

### `app/services/search/query_builder.py` (Quan trọng cho tối ưu Search)
- **Logic:** Xây dựng Hybrid Search Query cho Elasticsearch kết hợp BM25 và k-NN (Vector Search).
- **BM25 (Text Match):** Boost mạnh vào `base_name` (5x) và `name`/`brand` (3x).
- **k-NN (Vector Match):** Sử dụng `name_vector` để tìm kiếm ngữ nghĩa, có kèm theo `filter` cứng về thể tích (size_value_ml).
- **Soft Boosting (Should):** Đưa Brand, Category và Packaging vào `should` clause. Nghĩa là nếu khớp thì cộng thêm điểm cực lớn (boost: 50/30/20), nếu không khớp vẫn không loại bỏ sản phẩm (tránh empty results).
- **Hard Filter:** Thể tích (Size) được coi là filter cứng với sai số 5% để đảm bảo đúng nhu cầu người dùng.

### `app/services/search/es_service.py`
- **Logic:** Interface làm việc với Elasticsearch, thực hiện query và map kết quả về object.

---

## 4. Lớp Xếp hạng & Ra quyết định (Ranking & Decision Layer)

### `app/services/ranker/scoring.py` (Trái tim của Logic Code Review)
- **Logic:** Thực hiện Re-scoring dựa trên tập luật (Rule-based) sau khi có kết quả từ ES. Đây là nơi "uốn nắn" kết quả tìm kiếm.
- **Hệ thống điểm thưởng/phạt:**
    - Brand Match: +100 điểm (Rất quan trọng).
    - Category Match: +50 điểm.
    - Size/Unit Match: +30 điểm (thưởng) hoặc -40 điểm (phạt nếu sai lệch lớn).
    - Attributes (Zero, Diet...): +/- 10 điểm dựa trên mỗi tag khớp.
    - Best Seller: +1 điểm (dùng làm tie-breaker khi các thông số khác bằng nhau).

### `app/services/ranker/engine.py`
- **Logic:** Quyết định xem kết quả là "Khớp hoàn toàn" hay "Cần làm rõ".
- **Công thức Confidence:** Sử dụng hàm Sigmoid dựa trên khoảng cách điểm (Gap) giữa vị trí số 1 và số 2.
- **Decision Logic:** 
    - `exact_match`: Khi `is_exact_request=True` (LLM xác nhận query rõ ràng), khớp mọi ràng buộc cứng, và Confidence > 0.9.
    - `needs_clarification`: Trả về 3 lựa chọn đa dạng (Best seller, To nhất, Nhỏ nhất) nếu không đủ tự tin chọn 1.

---

## 5. Lớp Tiện ích (Utils)

### `app/utils/unit_converter.py`
- **Logic:** Chuyển đổi mọi đơn vị thể tích (l, ml, chai, lon) về `ml` để tính toán toán học chính xác trong bộ lọc và scoring.

### `app/utils/synonyms.py`
- **Logic:** Hard-coded map các từ lóng/từ địa phương (ví dụ: "bò húc" -> "red bull") trước khi đưa vào pipeline để tăng độ chính xác bóc tách.

---

## Tóm tắt cho Reviewer
- **Nếu muốn tối ưu độ chính xác bóc tách:** Sửa `app/prompts/extraction_v1.yaml`.
- **Nếu muốn tối ưu kết quả tìm kiếm (Recall):** Sửa `app/services/search/query_builder.py` (chỉnh boost/should clauses).
- **Nếu muốn tối ưu việc chọn sản phẩm (Precision):** Sửa trọng số trong `app/services/ranker/scoring.py`.
- **Nếu muốn đổi luồng xử lý:** Sửa `app/graph/pipeline.py`.
