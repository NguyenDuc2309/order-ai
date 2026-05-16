Vấn đề cốt lõi: "Không có sản phẩm" là một kết quả hợp lệ, không phải lỗi
Search query: "iPhone 15 Pro màu xanh 512GB"

Scenario A: Có trong catalog, còn hàng      → Trả về sản phẩm ✅
Scenario B: Có trong catalog, hết hàng      → ❓
Scenario C: Không có trong catalog          → ❓
Scenario D: Query mơ hồ, không match gì    → ❓
Vấn đề là nhiều hệ thống đang gộp B, C, D làm một — đây là nguồn gốc của critical issue.

Tại sao lại xảy ra critical issue này?
Vì hệ thống được thiết kế với assumption sai ngay từ đầu:

❌ "Search = phải có kết quả"

Dẫn đến các anti-pattern:
Anti-pattern 1: Hết hàng → vẫn hiển thị → user order → fulfill fail
Anti-pattern 2: Không có → trả về sản phẩm "gần giống" → mislead user
Anti-pattern 3: AI cố tìm ra cái gì đó để trả về → false confidence cao
                vì model không được train để abstain

Phân tách rõ 4 trạng thái — không được gộp
┌─────────────────────┬──────────────────────────────┬─────────────────────┐
│ Trạng thái          │ Behavior đúng                │ AI có nên search?   │
├─────────────────────┼──────────────────────────────┼─────────────────────┤
│ Có hàng, match tốt  │ Trả về + badge nếu đủ conf  │ Có                  │
│ Có hàng, match kém  │ Trả về, không badge          │ Có                  │
│ Hết hàng            │ Nói rõ "hết hàng" + suggest │ Có, nhưng filter    │
│ Không có trong hệ   │ Nói thật "không có"          │ Không nên hallucin. │
└─────────────────────┴──────────────────────────────┴─────────────────────┘
Hết hàng và không có là hai case hoàn toàn khác nhau về mặt logic nghiệp vụ và về mặt UX.

Về câu hỏi benchmark: Output = Expected hay thực tế?
Đây là điểm quan trọng nhất.
Sai lầm phổ biến khi benchmark
Expected output: [sản phẩm A, sản phẩm B]
Actual output:   []  (không có sản phẩm)

→ Đánh giá: FAIL ❌
Nhưng nếu thực tế hàng đã hết thì output = [] là ĐÚNG.
Đánh giá fail trong case này là benchmark đang đo sai thứ.
Cách benchmark đúng
Benchmark phải đo behavior đúng với state thực tế của hệ thống, không phải so với expected output tĩnh được viết lúc setup test:
Test case phải có context:

{
  query: "iPhone 15 Pro xanh 512GB",
  catalog_state: "hết hàng",          ← state thực tế lúc test
  expected_behavior: "trả về hết hàng + suggest alternative",
  NOT expected_output: "[product_id_123]"  ← cái này stale
}
Expected output tĩnh chỉ hợp lệ khi catalog state được kiểm soát và cố định trong test environment.

Về việc "trả về không có là để thể hiện logic"
Đúng — nhưng phải phân biệt rõ hai loại "không có":
Loại 1: Không có vì hệ thống hoạt động đúng
        → Hết hàng, không có trong catalog
        → Đây là CORRECT behavior, nên được benchmark đánh giá PASS

Loại 2: Không có vì hệ thống fail
        → Search engine lỗi, pipeline chết, timeout
        → Đây mới là FAIL thật sự
Nếu benchmark không phân biệt được hai loại này → benchmark đó đang đo nhầm, và sẽ tạo ra pressure sai cho team — ép AI phải "luôn trả về gì đó" thay vì trả về đúng.

Thiết kế đúng để tránh critical issue
Search pipeline phải có inventory gate độc lập:

Query
  │
  ▼
[Search + Rank]          ← AI làm việc này
  │
  ▼
[Inventory Filter]       ← KHÔNG phải AI, là service độc lập
  │                         real-time check tồn kho
  ├─ còn hàng  → pass
  └─ hết hàng  → tách ra, xử lý riêng
  │
  ▼
[Result Builder]
  ├─ có kết quả  → trả về list
  ├─ hết hàng    → trả về "hết hàng" + notify/waitlist
  └─ không có    → trả về "không tìm thấy" + suggest category
Inventory check không được nằm trong AI pipeline — vì AI không có real-time state, còn hàng hay không là business data, không phải semantic data.

Tóm lại

"Không có sản phẩm" là expected output hợp lệ trong nhiều trường hợp, không phải lỗi
Critical issue xảy ra vì inventory không được tách khỏi search pipeline
Benchmark phải đo behavior theo state thực tế, không phải so với expected output tĩnh
AI không nên được phép "tự bịa ra kết quả" chỉ để tránh trả về rỗng — đó mới là lỗi thật sự