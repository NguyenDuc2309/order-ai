TÀI LIỆU GIẢI PHÁP: HỆ THỐNG TÌM KIẾM SẢN PHẨM THÔNG MINH

Core Engine: Google Gemini (LLM) & Elasticsearch (Vector DB)

1. TỔNG QUAN KIẾN TRÚC (ARCHITECTURE OVERVIEW)

Hệ thống hoạt động theo mô hình RAG (Retrieval-Augmented Generation) kết hợp Agentic Workflow. Thay vì chỉ dùng AI để trích xuất text, Gemini sẽ đóng vai trò là một "Reasoning Agent" (Tác tử suy luận), kết hợp với Elasticsearch để truy xuất và đánh giá kết quả.

Luồng dữ liệu (Data Flow):

User Input: "mua 2 chai coca lớn nhưng không lấy loại zero"

Gemini Extractor: Phân tích cú pháp, hiểu ngữ cảnh, trích xuất JSON có cấu trúc.

Query Builder: Chuyển JSON thành ngữ cảnh tìm kiếm Hybrid (Vector + Keyword) cho Elasticsearch.

Elasticsearch: Trả về Top 10 kết quả thô.

Gemini Reranker (Đánh giá & Quyết định): Gemini đối chiếu Top 10 với yêu cầu gốc, chấm điểm tự tin (Confidence Score).

Final Output: Quyết định trả về 1 sản phẩm (nếu tự tin 100%) hoặc 3 sản phẩm (nếu cần người dùng chọn).

2. XỬ LÝ CÁC "TỬ ĐIỂM" (CRITICAL POINTS HANDLING)

Để hệ thống không bị "gãy" trong thực tế, các tử điểm sau được giải quyết ngay từ khâu thiết kế:

Tử điểm 1: Dữ liệu Legacy không cấu trúc (Unstructured DB)

Vấn đề: DB cũ chỉ có trường product_name ("Coca Cola 330ml lon"), không có size, unit riêng biệt.

Giải pháp (Làm Offline lúc Indexing): \* Chạy Gemini/Script để phân rã tên sản phẩm trước khi đưa vào ES.

Input DB gốc: Coca Cola 1.5L

Lưu vào ES: { "base_name": "Coca Cola", "size_value": 1.5, "size_unit": "lít", "packaging": "chai", "vector_embedding": [...] }

Tử điểm 2: Thiếu thông tin (Missing Size/Unit) & Fallback

Vấn đề: Khách chỉ gõ "mua coca" (Không có đơn vị, không dung tích).

Giải pháp: \* Áp dụng Bảng quy tắc ngầm (Implicit Rules). Nếu Entity size = null, hệ thống tự động gán default_unit = "lon", default_size = "330ml" (dựa trên Best Seller).

Đồng thời, cờ is_ambiguous = True được bật lên để kích hoạt logic trả về 3 sản phẩm ở bước cuối.

Tử điểm 3: Đơn vị đóng gói phức tạp/ngữ nghĩa địa phương

Vấn đề: Khách gọi "1 lốc", "1 két", "1 thùng", "coca lớn", "coca nhỏ".

Giải pháp: Gemini xử lý ánh xạ ngay tại bước Extraction bằng System Prompt:

"1 lốc" $\rightarrow$ {"unit": "lốc", "equivalent": "6 lon"}

"coca lớn" $\rightarrow$ {"attributes": ["size_large"]} (ES sẽ boost điểm cho các size > 1L).

Tử điểm 4: Câu lệnh phủ định (Negative Constraints)

Vấn đề: "mua coca không lấy loại zero hay light". Các model Vector thường bị nhầm lẫn vì vẫn thấy chữ "zero".

Giải pháp: Gemini trích xuất riêng mảng must_not: ["zero", "light"]. Query Builder sẽ gài mảng này vào mục must_not của Elasticsearch để loại bỏ hoàn toàn các biến thể này.

3. CHIẾN LƯỢC PROMPT CHO GEMINI (EXTRACTION LAYER)

Thay vì chỉ trích xuất, Gemini được yêu cầu suy luận và chấm điểm ngữ cảnh.

System Prompt mô phỏng:

Bạn là chuyên gia phân tích đơn hàng. Hãy trích xuất thông tin từ câu nói của khách.
Trả về định dạng JSON nghiêm ngặt:
{
"product_name": "Tên gốc sản phẩm đã sửa lỗi chính tả",
"quantity": số lượng (mặc định 1 nếu không nói),
"unit_raw": "đơn vị khách nói (lốc, thùng, chai...)",
"attributes": ["ít đường", "lớn", "nhỏ"],
"must_not": ["từ khóa phủ định"],
"is_exact_request": boolean (True nếu khách chỉ định RÕ RÀNG dung tích và đóng gói, False nếu chung chung)
}

4. CHIẾN LƯỢC HYBRID SEARCH TRONG ELASTICSEARCH

Khi nhận JSON từ Gemini, Backend xây dựng Query:

Vector Search (Dense Vector): Tìm sự tương đồng ngữ nghĩa của product_name (Giải quyết lỗi đánh máy "Co ka", từ đồng nghĩa "nước có gas").

BM25 Keyword (Match/Term): Đảm bảo khớp chính xác các con số (VD: khách tìm 1.5L thì không thể ra kết quả 500ml).

Filters (Must_not): Loại bỏ các từ khóa phủ định đã được Gemini bóc tách.

5. LOGIC OUTPUT: CHIẾN LƯỢC 1 vs 3 (QUYẾT ĐỊNH TRẢ KẾT QUẢ)

Đây là chốt chặn cuối cùng. Sau khi ES trả về danh sách (ví dụ Top 5), Backend sử dụng bộ rules kết hợp cờ is_exact_request của Gemini để quyết định:

KỊCH BẢN A: TRẢ VỀ ĐÚNG 1 SẢN PHẨM (Độ tự tin 100%)

Điều kiện kích hoạt (Cần thỏa mãn TẤT CẢ):

Gemini trả về is_exact_request: true (Input có đủ tên + size/unit rõ ràng).

ES kết quả Top 1 có điểm số (Score) vượt trội so với Top 2 (khoảng cách > 20%).

Các thuộc tính trích xuất (size, unit) khớp 100% với metadata của kết quả Top 1.

Hành động: Trực tiếp chọn Top 1, tự động điền vào giỏ hàng.
UI Message: "Đã chọn 1 thùng Coca Cola 330ml (24 lon) cho bạn."

KỊCH BẢN B: TRẢ VỀ 3 SẢN PHẨM GỢI Ý (Không chắc chắn 100%)

Điều kiện kích hoạt (Chỉ cần thỏa 1 trong các điều kiện):

Khách hàng dùng từ ngữ mơ hồ ("mua coca", "coca lớn", "nước ngọt"). Cờ is_exact_request: false.

Khách dùng đơn vị nhưng kho có nhiều biến thể (Ví dụ: "coca chai" -> Kho có chai 390ml và chai 1.5L).

Kết quả Top 1, 2, 3 của ES có điểm số (Score) sàn sàn nhau.

Hành động:
Lấy Top 3 sản phẩm đa dạng nhất về Variants (Ưu tiên: 1 Best Seller, 1 Size lớn, 1 Size nhỏ) để hiển thị.
UI Message: "Mình tìm thấy các loại Coca sau, bạn muốn lấy loại nào?"

[Item 1]: Coca Cola Lon 330ml (Phổ biến nhất)

[Item 2]: Coca Cola Chai nhựa 1.5L (Size lớn)

[Item 3]: Coca Cola Zero Lon 330ml (Gợi ý thêm)

6. KIẾN TRÚC API (DỰ KIẾN)

// POST /api/v1/search/product
// Request
{
"query": "coca 1 lít rưỡi",
"user_id": "usr_123",
"context": "supermarket"
}

// Response - Kịch bản 100%
{
"status": "exact_match",
"confidence": 0.98,
"items": [
{
"id": "coca_15l_chai",
"name": "Coca Cola 1.5L Chai PET",
"quantity": 1
}
],
"message": "Đã tìm thấy sản phẩm chính xác."
}

// Response - Kịch bản không chắc chắn (Trả 3 items)
{
"status": "needs_clarification",
"confidence": 0.65,
"items": [
{ "id": "coca_330ml_lon", "name": "Coca Cola 330ml Lon" },
{ "id": "coca_15l_chai", "name": "Coca Cola 1.5L Chai" },
{ "id": "coca_390ml_chai", "name": "Coca Cola 390ml Chai" }
],
"message": "Bạn muốn chọn dung tích nào?"
}
