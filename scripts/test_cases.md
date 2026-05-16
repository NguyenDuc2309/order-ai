# Benchmark Test Cases

Chỉnh sửa file này để thêm / sửa / xóa test case. Benchmark runner tự đọc từ đây.

## DSL cột Expected

```
<type> [+term] [!term] [qty=N]
```

| Token | Ý nghĩa |
|---|---|
| `clarify` | Kỳ vọng `needs_clarification` (informational — không bị fail nếu actual khác) |
| `exact` | Kỳ vọng `exact_match` (informational — không bị fail nếu actual khác) |
| `no_result` | **Strict**: actual phải là `no_result`, nếu hallucinate sẽ FAIL |
| `+term` | Ít nhất 1 sản phẩm trong top kết quả **phải chứa** term này (chỉ check khi actual có items) |
| `!term` | **Không** sản phẩm nào trong top kết quả được chứa term này |
| `qty=N` | `items[0].quantity` phải bằng N (chỉ check khi actual có items) |

Từ nhiều chữ dùng `_` thay khoảng trắng: `+hảo_hảo` → tìm chuỗi `"hảo hảo"`.

## Nguyên tắc chấm điểm (theo `critical_issue.md`)

> "Không có sản phẩm" là output hợp lệ — không phải lỗi.

Pipeline FAIL khi **hallucinate** (trả items sai), không FAIL khi **trung thực** trả `no_result`.

| Tình huống | Phán quyết |
|---|---|
| HTTP error / timeout | FAIL — system fault |
| `expected=no_result` + actual=`no_result` | PASS |
| `expected=no_result` + actual=`clarify`/`exact` | **FAIL** (hallucination — system bịa kết quả thay vì abstain) |
| `expected=exact`/`clarify` + actual=`no_result` | PASS — system trung thực, catalog có thể chưa index |
| `expected=exact`/`clarify` + actual có items | Check `+`, `!`, `qty=` trên items |
| Type mismatch `exact` ↔ `clarify` | Informational, không fail |

**Nguyên tắc variant exclusion:** Nếu user không nhắc variant đặc biệt (light, zero, không đường, ít béo…)
mà hệ thống trả về variant đó → **FAIL**. Dùng `!term` để capture điều này.

---

## Test Cases

| ID | Group | Query | Expected | Notes |
|---|---|---|---|---|
| G1-01 | G1 Brand-only | coca cola | clarify +coca | Brand-only, nhiều variant → phải clarify và trả coca |
| G1-02 | G1 Brand-only | pepsi | clarify +pepsi | Brand-only soft drink |
| G1-03 | G1 Brand-only | tiger | clarify +tiger | Brand-only beer |
| G1-04 | G1 Brand-only | heineken | clarify +heineken | Brand-only beer |
| G1-05 | G1 Brand-only | vinamilk | clarify +vinamilk | Brand-only milk |
| G1-06 | G1 Brand-only | lavie | clarify +lavie | Brand-only water |
| G1-07 | G1 Brand-only | omo | clarify +omo | Brand-only detergent — top result phải là OMO, không phải sản phẩm random |
| G1-08 | G1 Brand-only | hảo hảo | clarify +hảo_hảo | Brand-only instant noodle |
| G2-01 | G2 Brand+Pack | coca lon | clarify +coca +lon | User nói "lon" → top result phải có coca + lon |
| G2-02 | G2 Brand+Pack | pepsi chai | clarify +pepsi +chai | Pepsi dạng chai |
| G2-03 | G2 Brand+Pack | tiger lon | clarify +tiger +lon | Tiger dạng lon |
| G2-04 | G2 Brand+Pack | bia lon | clarify +bia +lon | Bia lon category |
| G2-05 | G2 Brand+Pack | hao hao ly | clarify +hảo_hảo | CRITICAL: hệ thống đang trả xúc xích — phải FAIL |
| G2-06 | G2 Brand+Pack | mì ly | clarify +ly | Mì cốc/ly, không phải mì gói |
| G2-07 | G2 Brand+Pack | sữa hộp vinamilk | clarify +vinamilk +hộp | Vinamilk dạng hộp |
| G2-08 | G2 Brand+Pack | nước suối chai | clarify +chai | Nước khoáng dạng chai |
| G3-01 | G3 Qty+Brand | 2 lon coca | exact +coca +lon !light !zero !không_đường qty=2 | User không nhắc Light/Zero → trả Light là FAIL |
| G3-02 | G3 Qty+Brand | 3 chai pepsi | exact +pepsi +chai qty=3 | Pepsi chai |
| G3-03 | G3 Qty+Brand | 6 lon bia tiger | exact +tiger +lon qty=6 | Tiger lon |
| G3-04 | G3 Qty+Brand | 2 thùng bia heineken | exact +heineken qty=2 | Heineken thùng |
| G3-05 | G3 Qty+Brand | 5 gói mì hảo hảo | exact +hảo_hảo qty=5 | Gói mì Hảo Hảo |
| G3-06 | G3 Qty+Brand | 4 hộp sữa vinamilk 1l | exact +vinamilk qty=4 | Vinamilk 1L |
| G3-07 | G3 Qty+Brand | 3 lon nước tăng lực sting | exact +sting +lon qty=3 | Sting lon |
| G3-08 | G3 Qty+Brand | 2 chai nước suối lavie | exact +lavie +chai qty=2 | LaVie chai |
| G3-09 | G3 Qty+Brand | 2 chai coca lớn | exact +coca +chai qty=2 | Chai lớn = chai 1.5L hoặc 2.25L, không phải lon |
| G3-10 | G3 Qty+Brand | 1 thùng coca | exact +coca qty=1 | Thùng coca |
| G3-11 | G3 Qty+Brand | 4 gói snack oishi | exact +oishi qty=4 | Oishi snack |
| G3-12 | G3 Qty+Brand | 3 hộp sữa tươi th | exact +th qty=3 | TH True Milk |
| G3-13 | G3 Qty+Brand | cho tôi 2 lon coca | exact +coca +lon !light !zero qty=2 | Phong cách nhờ — same expectation với G3-01 |
| G3-14 | G3 Qty+Brand | lấy 6 lon bia tiger | exact +tiger +lon qty=6 | Phong cách ra lệnh — same expectation với G3-03 |
| G4-01 | G4 Category | bia | clarify | Category-only beer, nhiều brand |
| G4-02 | G4 Category | sữa tươi | clarify +sữa | Fresh milk, nhiều brand |
| G4-03 | G4 Category | nước ngọt | clarify | Soft drink category |
| G4-04 | G4 Category | mì ăn liền | clarify | Instant noodle category |
| G4-05 | G4 Category | nước mắm | clarify +nước_mắm | Fish sauce, must return nước mắm products |
| G4-06 | G4 Category | snack | clarify +snack | Snack category |
| G5-01 | G5 Colloquial | bò húc | clarify | Tiếng lóng của Red Bull |
| G5-02 | G5 Colloquial | mì tôm | clarify | Tiếng lóng mì ăn liền |
| G5-03 | G5 Colloquial | coke | clarify +coca | English nickname của Coca Cola |
| G5-04 | G5 Colloquial | nước rửa chén | clarify | Category-only query, không ép brand cụ thể |
| G5-05 | G5 Colloquial | bột giặt | clarify | Category-only query, không ép brand cụ thể |
| G5-06 | G5 Colloquial | 333 | clarify | Bia 333 |
| G5-07 | G5 Colloquial | mì gói | clarify | Gói mì = mì ăn liền |
| G5-08 | G5 Colloquial | tương ớt | clarify | Hot sauce category |
| G6-01 | G6 Variant | coca thường | exact +coca !light !zero !không_đường | "Thường" = regular, variant đặc biệt bị cấm |
| G6-02 | G6 Variant | 2 lon coca bình thường | exact +coca +lon !light !zero !không_đường qty=2 | "Bình thường" = regular can |
| G6-03 | G6 Variant | pepsi thường | exact +pepsi !không_calo !light | Regular Pepsi |
| G6-04 | G6 Variant | sữa tươi nguyên kem | clarify +sữa !tách_béo !ít_béo | Full fat, không được trả ít béo |
| G6-05 | G6 Variant | bia tiger thường | clarify +tiger !silver !crystal | Tiger thường, không phải Silver/Crystal |
| G6-06 | G6 Variant | nước suối thường | clarify +lavie !sparkling !có_ga | Nước suối không ga |
| G7-01 | G7 No-result | iphone | no_result | Điện tử — ngoài catalog |
| G7-02 | G7 No-result | vitamin C | no_result | Thực phẩm chức năng — ngoài catalog |
| G7-03 | G7 No-result | áo thun nam | no_result | Quần áo — ngoài catalog |
| G7-04 | G7 No-result | sữa rửa mặt | no_result | Mỹ phẩm — ngoài catalog |
| G7-05 | G7 No-result | thuốc cảm | no_result | Thuốc — ngoài catalog |
| G7-06 | G7 No-result | bia không cồn | no_result | Bia không cồn không có trong catalog |
| G8-01 | G8 Complex | 2 chai nước cam | clarify qty=2 | Brand không xác định → phải hỏi lại |
| G8-02 | G8 Complex | mấy lon bia tiger | clarify +tiger | Số lượng mơ hồ → clarify |
| G8-03 | G8 Complex | bia uống cho mát | clarify +bia | Câu hỏi casual, không có số lượng/brand cụ thể |
| G8-04 | G8 Complex | nước uống cho bé | clarify | Yêu cầu clarify loại sản phẩm |
| G8-05 | G8 Complex | mì cay hảo hảo | clarify +hảo_hảo | Flavor attribute → clarify vì nhiều loại cay |
| G8-06 | G8 Complex | 2 lon coca với 3 gói mì | clarify | Multi-item query → phải clarify hoặc split |
| G8-07 | G8 Complex | mua 5 lon tiger | exact +tiger +lon qty=5 | "mua" là prefix không liên quan, phải extract đúng |
| G8-08 | G8 Complex | lấy cho tôi 1 thùng heineken | exact +heineken qty=1 | Câu đầy đủ lịch sự, phải nhận ra thùng + brand |
