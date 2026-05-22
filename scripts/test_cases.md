# Benchmark Test Cases

Chỉnh sửa file này để thêm / sửa / xóa test case. Benchmark runner tự đọc từ đây.

## DSL cột Expected

```
<type> [+term] [!term]
```

| Token | Ý nghĩa |
|---|---|
| `clarify` | Kỳ vọng `needs_clarification` (informational — không bị fail nếu actual khác) |
| `exact` | Kỳ vọng `exact_match` (informational — không bị fail nếu actual khác) |
| `no_result` | **Strict**: actual phải là `no_result`, nếu hallucinate sẽ FAIL |
| `+term` | Ít nhất 1 sản phẩm trong top kết quả **phải chứa** term này (chỉ check khi actual có items) |
| `!term` | **Không** sản phẩm nào trong top kết quả được chứa term này |

Từ nhiều chữ dùng `_` thay khoảng trắng: `+hảo_hảo` → tìm chuỗi `"hảo hảo"`.

## Nguyên tắc chấm điểm

> "Không có sản phẩm" là output hợp lệ — không phải lỗi.

Pipeline FAIL khi **hallucinate** (trả items sai), không FAIL khi **trung thực** trả `no_result`.

| Tình huống | Phán quyết |
|---|---|
| HTTP error / timeout | FAIL — system fault |
| `expected=no_result` + actual=`no_result` | PASS |
| `expected=no_result` + actual=`clarify`/`exact` | **FAIL** (hallucination) |
| `expected=exact`/`clarify` + actual=`no_result` | PASS — catalog có thể chưa index |
| `expected=exact`/`clarify` + actual có items | Check `+` và `!` trên items |
| Type mismatch `exact` ↔ `clarify` | Informational, không fail |

**Nguyên tắc variant exclusion:** user không nhắc variant mà hệ thống trả variant → FAIL. Dùng `!term`.

---

## Test Cases

| ID | Group | Query | Expected | Notes |
|---|---|---|---|---|
| G1-01 | G1 Alias | bò húc | clarify | Tiếng lóng của Red Bull — phải nhận ra, không trả thịt bò |
| G1-02 | G1 Alias | coke | clarify +coca | English nickname → Coca Cola |
| G1-03 | G1 Alias | 333 | clarify | Brand = số — đừng đọc là số lượng |
| G1-04 | G1 Alias | mì tôm | clarify | Tiếng lóng mì ăn liền |
| G1-05 | G1 Alias | tương ớt | clarify | Gia vị — không clarify sang ngành hàng khác |
| G1-06 | G1 Alias | bò húc lon lớn | exact | Tiếng lóng + size_hint=large — phải resolve được Red Bull + large can |
| G2-01 | G2 Brand+Pack | coca lon | clarify +coca +lon | Kết quả phải có cả "coca" lẫn "lon" |
| G2-02 | G2 Brand+Pack | tiger lon | clarify +tiger +lon | Tiger dạng lon, không phải chai |
| G2-03 | G2 Brand+Pack | sữa hộp vinamilk | clarify +vinamilk +hộp | Vinamilk hộp giấy, không phải bịch |
| G2-04 | G2 Brand+Pack | heineken thùng | exact +heineken | Thùng = đóng gói rõ ràng — phải exact hoặc clarify |
| G2-05 | G2 Brand+Pack | hảo hảo ly | clarify +hảo_hảo | Mì cốc/ly — packaging "ly" phân biệt với gói |
| G2-06 | G2 Brand+Pack | bia lon sài gòn | clarify +sài_gòn +lon | Bia Sài Gòn dạng lon |
| G2-07 | G2 Brand+Pack | lốc 6 coca | clarify +coca | Lốc = packaging, 6 = pack_count bị bỏ qua — phải vẫn tìm được coca |
| G2-08 | G2 Brand+Pack | nước mắm chai | clarify +nước_mắm | Nước mắm đóng chai, không phải túi |
| G3-01 | G3 Full-spec | 2 lon coca | exact +coca +lon !light !zero !không_đường | Số lượng bị bỏ; variant không được xuất hiện |
| G3-02 | G3 Full-spec | 2 thùng bia heineken | exact +heineken | Thùng = packaging rõ |
| G3-03 | G3 Full-spec | 4 hộp sữa vinamilk 1l | exact +vinamilk | Size 1L phải được đưa vào scoring |
| G3-04 | G3 Full-spec | 2 chai coca lớn | exact +coca +chai | Lớn → size_hint=large, chai ≠ lon — phải trả chai không phải lon |
| G3-05 | G3 Full-spec | 1 thùng coca | exact +coca | Thùng coca |
| G3-06 | G3 Full-spec | heineken lon 330ml | exact +heineken +lon | Exact size 330ml — phải khớp size_value |
| G3-07 | G3 Full-spec | thùng 24 lon tiger | exact +tiger | 24 là pack_count không phải số lượng đặt — đừng confuse |
| G3-08 | G3 Full-spec | sữa tươi tiệt trùng vinamilk hộp nhỏ | exact +vinamilk +hộp | Full spec — size_hint=small + packaging hộp |
| G4-01 | G4 Category | nước mắm | clarify +nước_mắm | Category thuần, phải trả đúng nước mắm |
| G4-02 | G4 Category | bia lon | clarify +lon | Danh mục + packaging |
| G4-03 | G4 Category | nước suối không có ga | clarify !có_ga !sparkling | must_not phải fire khi dùng "không có ga" |
| G4-04 | G4 Category | sữa tươi ít béo | clarify +sữa | Attribute "ít béo" → phải trả sữa ít béo không phải nguyên kem |
| G4-05 | G4 Category | snack oishi | clarify +oishi | Danh mục + brand |
| G5-01 | G5 Variant | coca thường | exact +coca !light !zero !không_đường | "Thường" → must_not đầy đủ cho coca |
| G5-02 | G5 Variant | 2 lon coca bình thường | exact +coca +lon !light !zero !không_đường | Cả số lượng bị bỏ lẫn variant bị loại |
| G5-03 | G5 Variant | bia tiger thường | clarify +tiger !silver !crystal | Tiger thường ≠ Tiger Silver / Crystal |
| G5-04 | G5 Variant | sữa tươi nguyên kem | clarify +sữa !tách_béo !ít_béo | "Nguyên kem" = full fat → loại trừ các loại ít béo |
| G5-05 | G5 Variant | heineken bình thường | clarify +heineken !silver | Heineken thường ≠ Heineken Silver |
| G5-06 | G5 Variant | pepsi không zero không light | exact +pepsi !zero !không_calo !light | Double negation — cả hai must_not phải được extract |
| G5-07 | G5 Variant | bia sài gòn thường không phải đặc biệt | clarify +sài_gòn !đặc_biệt | Explicit negation tên variant |
| G6-01 | G6 Name-trap | trà bí đao coca la hán quả | clarify +trà !cola | Tên sản phẩm có chữ "coca" nhưng brand là FUZETEA — phải trả trà, không phải Coca Cola |
| G6-02 | G6 Name-trap | trà xanh 0 độ | clarify +trà | "0 độ" là tên thương hiệu trà xanh, không phải alcohol=0 |
| G6-03 | G6 Name-trap | nước tăng lực monster | clarify +monster | Monster có trong catalog — trả đúng sản phẩm |
| G6-04 | G6 Name-trap | sting đỏ | clarify +sting | Sting màu đỏ — flavor attribute, không phải brand khác |
| G7-01 | G7 No-result | bia không cồn | no_result | Bia không cồn không có trong catalog |
| G7-02 | G7 No-result | thuốc cảm | no_result | Dược phẩm — ngoài scope |
| G7-03 | G7 No-result | sữa rửa mặt | clarify +sữa_rửa_mặt | Có trong catalog — phải trả sữa rửa mặt |
| G7-04 | G7 No-result | lavie có ga | no_result | Nước LaVie có gas — variant này không có trong catalog |
| G7-05 | G7 No-result | sữa ensure | clarify +ensure | Ensure có trong catalog — phải trả đúng sản phẩm |
| G7-06 | G7 No-result | bia 0 độ | no_result | Phiên bản khác của bia không cồn — hallucinate nếu trả kết quả |
| G7-07 | G7 No-result | nước tăng lực không đường | no_result | Variant không tồn tại trong catalog |
| G8-01 | G8 Complex | lấy cho tôi 1 thùng heineken | exact +heineken | Câu lịch sự đầy đủ — filler words phải bị gỡ |
| G8-02 | G8 Complex | 2 lon coca với 3 gói mì | clarify | Multi-item query — phải clarify hoặc chỉ xử lý 1 sản phẩm |
| G8-03 | G8 Complex | mì cay hảo hảo | clarify +hảo_hảo | Flavor attribute + brand |
| G8-04 | G8 Complex | cho tôi hộp sữa nhỏ vinamilk | exact +vinamilk +hộp | Câu nhờ + size_hint=small |
| G8-05 | G8 Complex | mua bia heineken nhưng không lấy loại bạc | exact +heineken !silver !bạc | Câu tự nhiên + explicit negation variant |
| G8-06 | G8 Complex | đặt giúp tôi vài lon pepsi loại thường | exact +pepsi +lon !không_calo !light | Filler "đặt giúp tôi vài" + variant exclusion |
| G8-07 | G8 Complex | sữa tươi không đường vinamilk hộp lớn | exact +vinamilk +hộp | Multi-constraint: brand + must_not + packaging + size |
| G8-08 | G8 Complex | bia gì uống cho mát hả | clarify +bia | Câu hỏi không có brand/size — phải clarify không no_result |
