# System Design — Order-AI

**Mục tiêu:** thay thế tìm kiếm truyền thống bằng pipeline AI hiểu ngôn ngữ tự nhiên. Nhận một câu query từ người dùng, trả về danh sách sản phẩm phù hợp với ý định của họ.

**Ranh giới:** hệ thống chỉ xử lý "sản phẩm nào phù hợp" — không phụ trách tồn kho, giá, khuyến mãi, hay giỏ hàng.

---

## 1. Luồng tổng quan

Khi client gửi một query (ví dụ: *"2 lon coca"*), yêu cầu đi qua bốn bước tuần tự trong một pipeline. Bốn bước đó là: trích xuất intent, xây query tìm kiếm, thực hiện tìm kiếm, và ra quyết định. Mỗi bước nhận đầu ra của bước trước và bổ sung thêm thông tin trước khi chuyển tiếp.

---

## 2. Bước 1 — Trích xuất intent (Extract)

Đây là bước quan trọng nhất. Toàn bộ pipeline phụ thuộc vào kết quả của bước này.

Khi nhận query, hệ thống chạy song song hai việc: gọi Gemini LLM để phân tích ý nghĩa câu query, đồng thời gọi Gemini Embedding để chuyển câu query thành một vector số học 768 chiều đại diện cho ngữ nghĩa của nó.

LLM nhận câu query và một hệ thống prompt được định nghĩa sẵn. Nó trả về một cấu trúc dữ liệu có tên **ExtractionResult**, gồm các trường:

- **product\_name** — tên sản phẩm mà người dùng muốn tìm, dùng làm từ khóa BM25.
- **brand** — thương hiệu được nhắc đến, nếu có. Đây là FACT: người dùng nói rõ.
- **category** — danh mục sản phẩm được suy ra bởi LLM. Đây là SUY ĐOÁN: chỉ dùng làm soft boost, không gate quyết định.
- **unit\_raw** — đơn vị đóng gói người dùng nói đến (lon, chai, hộp…). Đây là FACT.
- **size\_value và size\_unit** — kích thước cụ thể nếu được nhắc (330ml, 1L…). Đây là FACT.
- **size\_hint** — nhãn kích thước (lớn/nhỏ) được tính tự động từ size\_value trong rules.py, không do LLM tự đoán.
- **attributes** — danh sách thuộc tính tự do (cay, hữu cơ, không cồn…).
- **must\_not** — danh sách từ khóa bị loại trừ. Ví dụ nếu user nói "thường" thì must\_not sẽ gồm: light, zero, không đường, ít calo.

Sau khi LLM trả về, hệ thống chuẩn hóa trường brand: giải quyết các tên alias (ví dụ "pepsi co" → "pepsico"), rồi normalize về dạng lowercase không dấu để khớp chính xác với dữ liệu index.

Nếu LLM thất bại, hệ thống fallback bằng cách dùng toàn bộ câu query làm product\_name và để tất cả trường còn lại là null.

---

## 3. Bước 2 — Xây query tìm kiếm (Build Query)

Từ ExtractionResult và query vector vừa có, hệ thống xây một hybrid query cho Elasticsearch. Query này gồm bốn thành phần:

**BM25 keyword match** trên các trường text: tên đầy đủ, tên gốc (không có size/đóng gói), và tên thương hiệu. Trường tên gốc được ưu tiên cao hơn vì nó ít nhiễu hơn.

**Vector kNN** tìm 20 sản phẩm gần nhất theo cosine similarity trên name\_vector — bắt được những trường hợp người dùng nói khác nhưng ý giống nhau (tên lóng, viết tắt, sai chính tả).

**Soft boost** tăng điểm cho những sản phẩm khớp brand, category, và packaging với extraction — không dùng làm hard filter, chỉ đẩy thứ hạng lên.

**must\_not filter** loại những sản phẩm chứa từ khóa bị cấm trong extraction.

Kết quả là một query Elasticsearch hoàn chỉnh kết hợp cả keyword lẫn semantic, với điểm ưu tiên tập trung vào những sản phẩm khớp nhiều chiều nhất.

---

## 4. Bước 3 — Thực hiện tìm kiếm (Search)

Hệ thống gửi query vừa xây cho Elasticsearch và nhận về tối đa 20 kết quả, mỗi kết quả kèm theo raw score từ ES. Bước này không có logic phức tạp — nó chỉ đơn thuần thực thi tìm kiếm và chuyển kết quả sang bước tiếp theo.

---

## 5. Bước 4 — Ra quyết định (Decide)

Đây là bước phức tạp nhất. Nó gồm ba layer chạy tuần tự: ConstraintAuditor → StructuralScorer → Decider.

### Layer 1 — ConstraintAuditor

Với mỗi sản phẩm trong 20 kết quả, auditor kiểm tra từng constraint mà extraction đã chỉ định. Mỗi constraint (brand, category, size, packaging, attributes, must\_not) được chấm một trong ba trạng thái: MATCH, MISMATCH, hoặc NOT\_SPECIFIED.

Từ đó tính hai chỉ số tổng hợp:

- **hard\_pass**: sản phẩm không vi phạm brand hay must\_not — đây là điều kiện cần tối thiểu để sản phẩm có thể là kết quả đúng. Category không nằm trong hard\_pass vì là SUY ĐOÁN của LLM (P1).
- **soft\_pass**: hard\_pass cộng thêm size và packaging đều khớp — nghĩa là sản phẩm đáp ứng đầy đủ các điều kiện cứng lẫn mềm.
- **satisfied\_count / specified\_count**: tỉ lệ bao nhiêu constraint được thỏa trên tổng số constraint user đã chỉ định.

### Layer 2 — StructuralScorer

Lấy raw score từ ES làm điểm gốc, cộng/trừ điểm dựa trên kết quả audit:

- Brand khớp: cộng 100. Brand sai: trừ 50.
- Category khớp: cộng 50. Category sai: trừ 20.
- Size khớp: cộng 30. Size sai: trừ 40.
- Packaging khớp: cộng 10. Packaging sai: trừ 20.
- Attributes: cộng điểm theo tỉ lệ số attribute khớp.

Ngoài ra có một **variant penalty**: nếu một sản phẩm chứa variant token (light, zero, diet, không đường, sparkling…) mà query không nhắc đến variant đó, sản phẩm bị trừ 50 điểm. Điều này ngăn hệ thống gợi ý Coca Zero khi user chỉ nói "coca".

Sau bước này, 20 sản phẩm có thứ tự mới dựa trên structural score, phản ánh mức độ khớp thực sự với intent thay vì chỉ dựa vào text similarity.

### Layer 3 — Decider (AND Gate)

Decider nhìn vào toàn bộ danh sách đã được score và đưa ra một trong ba quyết định:

**no\_result** — không trả sản phẩm nào. Kích hoạt khi:
- Không có sản phẩm nào trong kết quả.
- Tất cả sản phẩm đều không thỏa bất kỳ constraint nào mà user đã chỉ định.
- Brand bị MISMATCH, sản phẩm khớp rất ít constraint, và điểm thấp.
- User yêu cầu attribute tiêu cực (ví dụ "không cay") nhưng không có sản phẩm nào phù hợp.
- Điểm quá thấp và user không chỉ định constraint nào rõ ràng.

no\_result là câu trả lời trung thực — hệ thống thà nói "không tìm thấy" còn hơn trả về sản phẩm sai.

**exact\_match** — trả về đúng một sản phẩm. Kích hoạt khi đồng thời: sản phẩm đứng đầu đạt hard\_pass, khoảng cách điểm giữa sản phẩm đứng đầu và đứng thứ hai vượt ngưỡng (nghĩa là sản phẩm số một rõ ràng tốt hơn hẳn), và tỉ lệ constraint thỏa từ 0.8 trở lên. Khi có exact\_match, client có thể thêm sản phẩm vào giỏ ngay mà không cần hỏi thêm.

**needs\_clarification** — trả về 2-3 sản phẩm để user chọn. Đây là mặc định khi không đủ điều kiện cho exact\_match và không phải no\_result. Hệ thống chọn các sản phẩm đại diện theo độ đa dạng size (lớn nhất, nhỏ nhất, trung bình), đồng thời lọc bỏ variant products trước khi chọn để tránh trả về toàn Coca Zero.

### Tính điểm confidence

Confidence là số thực trong khoảng [0.01, 0.99], phản ánh mức độ chắc chắn của quyết định. Được tính kết hợp hai yếu tố: khoảng cách điểm giữa top-1 và top-2 (đo bằng sigmoid để giảm biên độ), và tỉ lệ constraint thỏa. Confidence cao nghĩa là quyết định rõ ràng; confidence thấp nghĩa là kết quả mơ hồ.

---

## 6. Kết quả trả về

Sau khi qua bốn bước, hệ thống trả về một response với:

- **type**: một trong ba giá trị — exact\_match, needs\_clarification, no\_result.
- **confidence**: độ chắc của quyết định.
- **items**: danh sách sản phẩm (1 item nếu exact\_match, 2-3 nếu needs\_clarification, rỗng nếu no\_result), mỗi item gồm ID, tên và điểm. Không có số lượng — đây là trách nhiệm của downstream service.
- **message**: câu thông báo cho UI hiển thị cho người dùng.

---

## 7. Dữ liệu trong Elasticsearch

Index lưu thông tin catalog sản phẩm — dữ liệu thay đổi chậm. Mỗi document có các trường text để BM25 tìm kiếm, các trường keyword để filter và boost, các trường số để so sánh size, và một vector 768 chiều cho kNN semantic search.

Hệ thống **không** lưu tồn kho, giá, hay trạng thái khuyến mãi trong ES. Ba loại dữ liệu này thay đổi theo từng transaction và không thể giữ sync với vector store — chúng thuộc về downstream service, nằm ngoài scope của Order-AI.

---

## 8. Ghi log và quan sát

Mỗi query được ghi lại đầy đủ vào file log dạng JSON: câu query gốc, kết quả extraction, kết quả audit của sản phẩm đứng đầu, và quyết định cuối cùng kèm lý do. Log này dùng để debug, phân tích lỗi, và theo dõi chất lượng pipeline theo thời gian.

---

## 9. Chất lượng và giới hạn hiện tại

Hệ thống hiện đạt 85.94% trên bộ 64 test case trải đều 8 nhóm: brand match, số lượng, danh mục, cách nói thông thường, variant, out-of-catalog, và query phức tạp.

Scoring contract: no\_result là câu trả lời đúng khi sản phẩm không tồn tại trong catalog — không bị tính là thất bại. Thất bại chỉ xảy ra khi hệ thống trả về sản phẩm sai (hallucinate).

Các điểm yếu hiện tại:

- Một số query out-of-catalog vẫn chưa fire no\_result do LLM tìm được partial match gần đúng trong catalog. Hướng xử lý: tune prompt và hạ threshold.
- Một số sản phẩm chưa được index đủ dẫn đến miss. Hướng xử lý: index toàn bộ 2774 sản phẩm.
- Gate exact\_match chưa fire nhiều vì threshold gap đang đặt cao để an toàn. Hướng xử lý: tune sau khi có đủ dữ liệu thực tế.
