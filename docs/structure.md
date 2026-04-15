Cấu trúc này tập trung vào việc mô-đun hóa các thành phần chính: Bóc tách (Gemini), Truy vấn (Elasticsearch) và Đánh giá (Ranker).

```
ai-service/
├── app/
│   ├── api/                    # Quản lý các giao diện lập trình ứng dụng (API)
│   │   └── v1/
│   │       └── search.py       # Endpoint chính: tiếp nhận query và trả về 1 hoặc 3 kết quả
│   ├── core/                   # Cấu hình hệ thống và khởi tạo kết nối
│   │   ├── config.py           # Quản lý biến môi trường (.env), API Keys
│   │   └── clients/
│   │       ├── gemini.py       # Cấu hình kết nối Google Generative AI (Gemini)
│   │       └── elastic.py      # Cấu hình kết nối Elasticsearch (Vector DB)
│   ├── prompts/                # QUẢN LÝ PROMPT TẬP TRUNG (Dạng .yaml hoặc .txt)
│   │   ├── extraction_v1.yaml  # Prompt dùng để bóc tách thực thể (Product, Unit, Size, is_exact)
│   │   └── reranking_v1.yaml   # Prompt dùng để Gemini chấm điểm lại kết quả từ ES (nếu cần)
│   ├── services/               # LOGIC NGHIỆP VỤ (TRÁI TIM CỦA HỆ THỐNG)
│   │   ├── extractor/          # Layer xử lý với Gemini
│   │   │   ├── interface.py    # Định nghĩa lớp trừu tượng cho Extractor
│   │   │   └── gemini_parser.py# Logic gọi Gemini, xử lý JSON đầu ra và kiểm tra logic is_exact
│   │   ├── search/             # Layer xử lý với Elasticsearch
│   │   │   ├── query_builder.py# Chuyển đổi JSON thực thể thành DSL Query (Hybrid: Vector + Keyword)
│   │   │   └── es_service.py   # Thực thi truy vấn và nhận kết quả thô (Raw Hits)
│   │   └── ranker/             # BỘ NÃO QUYẾT ĐỊNH ĐẦU RA (1 HOẶC 3)
│   │       ├── engine.py       # Logic so sánh Score, kiểm tra độ tự tin để chốt số lượng kết quả
│   │       └── rules.py        # Các quy tắc nghiệp vụ (Fallback unit, Business default size)
│   ├── models/                 # Định nghĩa cấu trúc dữ liệu (Pydantic)
│   │   ├── request.py          # Schema dữ liệu đầu vào từ phía người dùng
│   │   ├── extraction.py       # Schema kết quả bóc tách từ Gemini
│   │   └── response.py         # Schema dữ liệu trả về (Single Match vs Multi Suggestions)
│   └── utils/                  # Tiện ích bổ sung
│       ├── text_norm.py        # Chuẩn hóa văn bản tiếng Việt, xử lý lỗi typo cơ bản
│       └── unit_converter.py   # Quy đổi đơn vị (Ví dụ: "thùng" -> 24 lon, "lít" -> 1000ml)
├── scripts/                    # Các kịch bản chạy độc lập (Offline)
│   └── data_enrichment.py      # Dùng AI quét DB cũ để tách tên/size/unit trước khi nạp vào ES
├── tests/                      # Kiểm thử tự động (Unit test cho Ranker và Extractor)
├── .env                        # Lưu trữ thông tin nhạy cảm (API_KEY, DB_URL)
├── .gitignore                  # Khai báo các file không đưa lên Git
├── main.py                     # Entry point của ứng dụng (Khởi tạo FastAPI)
├── README.md                   # Hướng dẫn vận hành và tài liệu dự án
└── requirements.txt            # Danh sách các thư viện Python cần thiết
```

### Giải thích các thư mục quan trọng:

1. **`app/prompts/`**: Tách riêng Prompt ra khỏi Code để bạn có thể cập nhật logic bóc tách của Gemini mà không cần khởi động lại Server hay build lại Docker.
    
2. **`app/services/ranker/`**: Đây là nơi chứa logic "Sàng lọc" chính. File `engine.py` sẽ chứa các điều kiện `if/else` về điểm số (Score) của Elasticsearch để quyết định xem kết quả là "Chắc chắn" hay "Cần gợi ý thêm".
    
3. **`app/services/search/query_builder.py`**: Chịu trách nhiệm tạo ra các câu truy vấn phức tạp. Nếu Gemini bóc ra `size: 1.5L`, Query Builder sẽ tạo ra một bộ lọc `must_match` trên trường `size` trong DB để đảm bảo tính chính xác.
    
4. **`scripts/data_enrichment.py`**: Đây là bước chuẩn bị. Nếu dữ liệu gốc trong Elasticsearch không "sạch" (không có trường Unit/Size riêng), script này sẽ dùng Gemini để "làm sạch" dữ liệu trước khi bạn bắt đầu chạy Service.