# Benchmark Test Cases

> **Scoring contract:** mọi rule đánh giá nằm ở [`docs/eval-goal.md`](../docs/eval-goal.md).
> File này chỉ định nghĩa **input + ground truth**. Sửa file này = sửa contract — chỉ
> sửa khi sai về spec, **không** sửa để pass benchmark.

---

## Schema (per-case)

Mỗi row trong các bảng dưới mang **8 trường ground truth** (mở rộng từ schema cũ):

| Cột | Bắt buộc | Ý nghĩa |
|---|---|---|
| `ID` | ✓ | Mã case duy nhất (vd `G1-01`, `INV-03`, `DIR-05`) |
| `Cap` | ✓ | Capability — một trong `C-ALIAS / C-BRAND / C-SPEC / C-CAT / C-VAR / C-TRAP / C-ABST / C-NL` |
| `Type` | ✓ | Test type — `MFT` / `INV` / `DIR` (xem [eval-goal §3](../docs/eval-goal.md#3-phân-loại-test-taxonomy)) |
| `Query` | ✓ | Câu input người dùng (UTF-8, dấu đầy đủ) |
| `Expected` | ✓ | DSL `<type>` + `+term` + `!term` (xem dưới) |
| `In-Cat` | ✓ | `true` nếu sản phẩm tồn tại trong catalog; `false` nếu out-of-catalog |
| `Top1` | ✓ | ID sản phẩm kỳ vọng ở rank-1 (TBD = chưa fix, runner skip Hit@1 cho case này) |
| `Gold` | ✓ | Slot ground truth — compact: `b:<brand>; u:<uom>; s:<size>; h:<size_hint>; n:<must_not_csv>; c:<category>` (bỏ field rỗng; `-` nếu không có slot nào) |
| `Notes` | – | Rationale cho người đọc |

### DSL cột Expected

```
<type> [+term] [!term]
```

| Token | Ý nghĩa |
|---|---|
| `clarify` | Kỳ vọng `needs_clarification` (**strict** — type mismatch FAIL nếu actual khác và in-catalog) |
| `exact` | Kỳ vọng `exact_match` (**strict** cho C-SPEC; informational cho C-NL/C-ALIAS) |
| `no_result` | actual phải là `no_result`, nếu trả items → FAIL (hallucination) |
| `+term` | Ít nhất 1 item top phải chứa term (chỉ áp dụng khi actual có items) |
| `!term` | Không item nào trong top được chứa term |

Từ nhiều chữ dùng `_`: `+hảo_hảo` → tìm `"hảo hảo"`.

> **Khác benchmark cũ:** type mismatch `exact ↔ clarify` **không còn informational** cho
> capability C-SPEC, C-BRAND, C-CAT. Lý do: nâng strict đo correctness thật (xem
> [PROB-020 → eval-goal §4.D](../docs/eval-goal.md#d-abstention-precisionrecall-no_result-như-task-riêng)).
> Riêng `actual=no_result` cho `expected=exact|clarify` chỉ PASS khi `In-Cat=false` —
> ngược lại FAIL (false abstention).

---

## MFT cases — Minimum Functionality (64)

### G1 — Alias / colloquial (C-ALIAS)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G1-01 | C-ALIAS | MFT | bò húc | clarify +red_bull | true | 10601161CHA | b:red_bull | Tiếng lóng Red Bull |
| G1-02 | C-ALIAS | MFT | coke | clarify +coca | true | 10011650LON | b:coca_cola | English nickname |
| G1-03 | C-ALIAS | MFT | 333 | clarify +333 | true | 10011891LON | b:333 | Brand = số |
| G1-04 | C-ALIAS | MFT | mì tôm | clarify +mì | true | 10007893G1 | c:mi_an_lien | Tiếng lóng mì ăn liền |
| G1-05 | C-ALIAS | MFT | tương ớt | clarify +tương_ớt | true | 10141822CHA | c:gia_vi | Gia vị |
| G1-06 | C-ALIAS | MFT | bò húc lon lớn | clarify +red_bull | true | 10601161CHA | b:red_bull; u:lon; h:large | Catalog chỉ có Red Bull chai (150ml/145ml) — không có lon → bỏ +lon |

### G2 — Brand + Packaging (C-BRAND)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G2-01 | C-BRAND | MFT | coca lon | clarify +coca +lon | true | 10011650LON | b:coca_cola; u:lon | Brand + packaging |
| G2-02 | C-BRAND | MFT | tiger lon | clarify +tiger +lon | true | 10170930LON | b:tiger; u:lon | Tiger dạng lon |
| G2-03 | C-BRAND | MFT | sữa hộp vinamilk | clarify +vinamilk +hộp | true | 10010487HOP | b:vinamilk; u:hộp | Hộp giấy |
| G2-04 | C-BRAND | MFT | heineken thùng | exact +heineken +thùng | true | 10012012T24 | b:heineken; u:thùng | Thùng rõ ràng |
| G2-05 | C-BRAND | MFT | hảo hảo ly | no_result | false | – | b:hảo_hảo; u:ly | Hảo Hảo không có dạng ly/cốc trong catalog |
| G2-06 | C-BRAND | MFT | bia lon sài gòn | clarify +sài_gòn +lon | true | 10197691LON | b:saigon; u:lon | Bia SG lon |
| G2-07 | C-BRAND | MFT | lốc 6 coca | clarify +coca | true | 10011650G6 | b:coca_cola; u:lốc | pack_count bỏ |
| G2-08 | C-BRAND | MFT | nước mắm chai | clarify +nước_mắm +chai | true | 10009164CHA | u:chai; c:nuoc_mam | Nước mắm chai |

### G3 — Full specification (C-SPEC)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G3-01 | C-SPEC | MFT | 2 lon coca | exact +coca +lon !light !zero !không_đường | true | 10011650LON | b:coca_cola; u:lon; n:light,zero,không_đường | Qty bỏ; variant exclude |
| G3-02 | C-SPEC | MFT | 2 thùng bia heineken | exact +heineken +thùng | true | 10012012T24 | b:heineken; u:thùng | Thùng rõ |
| G3-03 | C-SPEC | MFT | 4 hộp sữa vinamilk 1l | exact +vinamilk +hộp | true | 10010487HOP | b:vinamilk; u:hộp; s:1000ml | Size 1L scoring |
| G3-04 | C-SPEC | MFT | 2 chai coca lớn | exact +coca +chai | true | 10011250CHA | b:coca_cola; u:chai; h:large | size_hint=large; chai ≠ lon |
| G3-05 | C-SPEC | MFT | 1 thùng coca | no_result | false | – | b:coca_cola; u:thùng | Catalog chỉ có Coca Zero thùng (10011651T) — Coca thường không có uom=Thùng |
| G3-06 | C-SPEC | MFT | heineken lon 330ml | exact +heineken +lon | true | 10012012LON | b:heineken; u:lon; s:330ml | Exact size match |
| G3-07 | C-SPEC | MFT | thùng 24 lon tiger | exact +tiger +thùng | true | 10170930T24 | b:tiger; u:thùng | 24 là pack_count |
| G3-08 | C-SPEC | MFT | sữa tươi tiệt trùng vinamilk hộp nhỏ | exact +vinamilk +hộp | true | 10010488G4 | b:vinamilk; u:hộp; h:small | size_hint=small |

### G4 — Category-only (C-CAT)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G4-01 | C-CAT | MFT | nước mắm | clarify +nước_mắm | true | 10009164CHA | c:nuoc_mam | Category thuần |
| G4-02 | C-CAT | MFT | bia lon | clarify +bia +lon | true | 10012012LON | u:lon; c:bia | Danh mục + uom |
| G4-03 | C-CAT | MFT | nước suối không có ga | clarify +nước_suối !có_ga !sparkling | true | 10011640CHA | c:nuoc_suoi; n:có_ga,sparkling | must_not phải fire |
| G4-04 | C-CAT | MFT | sữa tươi ít béo | clarify +sữa +ít_béo | true | 10405704HOP | c:sua_tuoi; a:ít_béo | Attribute "ít béo" |
| G4-05 | C-CAT | MFT | snack oishi | clarify +oishi | true | 10015795G1 | b:oishi; c:snack | Danh mục + brand |

### G5 — Variant exclusion (C-VAR)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G5-01 | C-VAR | MFT | coca thường | exact +coca !light !zero !không_đường | true | 10011650LON | b:coca_cola; n:light,zero,không_đường,diet | "Thường" → full must_not |
| G5-02 | C-VAR | MFT | 2 lon coca bình thường | exact +coca +lon !light !zero !không_đường | true | 10011650LON | b:coca_cola; u:lon; n:light,zero,không_đường,diet | Qty bỏ + variant |
| G5-03 | C-VAR | MFT | bia tiger thường | clarify +tiger !silver !crystal | true | 10170930LON | b:tiger; n:silver,crystal | Tiger ≠ Silver/Crystal |
| G5-04 | C-VAR | MFT | sữa tươi nguyên kem | clarify +sữa !tách_béo !ít_béo | true | 10010487HOP | c:sua_tuoi; n:tách_béo,ít_béo; a:nguyên_kem | Full fat |
| G5-05 | C-VAR | MFT | heineken bình thường | clarify +heineken !silver | true | 10012012LON | b:heineken; n:silver | Heineken ≠ Silver |
| G5-06 | C-VAR | MFT | pepsi không zero không light | exact +pepsi !zero !không_calo !light | true | 10011759LON | b:pepsi; n:zero,không_calo,light | Double negation |
| G5-07 | C-VAR | MFT | bia sài gòn thường không phải đặc biệt | clarify +sài_gòn !đặc_biệt | true | 10197691LON | b:saigon; n:đặc_biệt | Explicit negation |

### G6 — Name trap (C-TRAP)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G6-01 | C-TRAP | MFT | trà bí đao coca la hán quả | clarify +trà !cola | true | 10150201LON | b:fuzetea; c:tra | Brand=FUZETEA, không phải Coca |
| G6-02 | C-TRAP | MFT | trà xanh 0 độ | no_result | false | – | b:0_do; c:tra_xanh | Brand '0 Độ' không có trong catalog Winmart |
| G6-03 | C-TRAP | MFT | nước tăng lực monster | clarify +monster | true | 10324843LON | b:monster; c:nuoc_tang_luc | Monster có trong catalog |
| G6-04 | C-TRAP | MFT | sting đỏ | clarify +sting | true | 10056551LON | b:sting; a:đỏ | "Đỏ" = flavor attribute |

### G7 — Abstention / no_result (C-ABST)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G7-01 | C-ABST | MFT | bia không cồn | no_result | false | – | c:bia; n:cồn | Bia không cồn không có |
| G7-02 | C-ABST | MFT | thuốc cảm | no_result | false | – | c:duoc_pham | Out of scope |
| G7-03 | C-CAT | MFT | sữa rửa mặt | clarify +sữa_rửa_mặt | true | 10161716TUY | c:sua_rua_mat | Có trong catalog |
| G7-04 | C-ABST | MFT | lavie có ga | no_result | false | – | b:lavie; a:có_ga | LaVie có gas không có |
| G7-05 | C-BRAND | MFT | sữa ensure | clarify +ensure | true | 10198115CHA | b:ensure | Ensure có trong catalog |
| G7-06 | C-ABST | MFT | bia 0 độ | no_result | false | – | c:bia; n:cồn | Bia không cồn variant |
| G7-07 | C-ABST | MFT | nước tăng lực không đường | no_result | false | – | c:nuoc_tang_luc; n:đường | Variant không tồn tại |

### G8 — Complex / natural language (C-NL)

| ID | Cap | Type | Query | Expected | In-Cat | Top1 | Gold | Notes |
|---|---|---|---|---|---|---|---|---|
| G8-01 | C-NL | MFT | lấy cho tôi 1 thùng heineken | exact +heineken +thùng | true | 10012012T24 | b:heineken; u:thùng | Câu lịch sự + filler |
| G8-02 | C-NL | MFT | 2 lon coca với 3 gói mì | clarify | true | TBD | b:coca_cola; u:lon | Multi-item — clarify |
| G8-03 | C-NL | MFT | mì cay hảo hảo | clarify +hảo_hảo | true | 10007893G1 | b:hảo_hảo; a:cay | Flavor + brand |
| G8-04 | C-NL | MFT | cho tôi hộp sữa nhỏ vinamilk | exact +vinamilk +hộp | true | 10010488G4 | b:vinamilk; u:hộp; h:small | Câu nhờ + size_hint |
| G8-05 | C-NL | MFT | mua bia heineken nhưng không lấy loại bạc | exact +heineken !silver !bạc | true | 10012012LON | b:heineken; n:silver,bạc | NL + variant negation |
| G8-06 | C-NL | MFT | đặt giúp tôi vài lon pepsi loại thường | exact +pepsi +lon !không_calo !light | true | 10011759LON | b:pepsi; u:lon; n:không_calo,light | Filler + variant |
| G8-07 | C-NL | MFT | sữa tươi không đường vinamilk hộp lớn | exact +vinamilk +hộp | true | 10010491HOP | b:vinamilk; u:hộp; h:large; n:đường | Multi-constraint |
| G8-08 | C-NL | MFT | bia gì uống cho mát hả | clarify +bia | true | TBD | c:bia | Câu hỏi không brand/size |

---

## INV cases — Invariance (8 pairs)

> Mỗi case là một **cặp** `(Query A, Query B)` phải cho cùng `type` và cùng top-1 id.
> Pipeline FAIL nếu type khác **hoặc** top-1 id khác. Đo bằng `Behavioral Invariance Pass Rate`
> ([eval-goal §4.E](../docs/eval-goal.md#e-behavioral-invariance-pass-rate)).

| ID | Cap | Anchor | Query A | Query B | Invariant | Notes |
|---|---|---|---|---|---|---|
| INV-01 | C-NL | G2-01 | coca lon | cho tôi coca lon | type + top1 | INV-1 filler |
| INV-02 | C-BRAND | G2-01 | coca lon | lon coca | type + top1 | INV-2 token order |
| INV-03 | C-NL | G3-01 | 2 lon coca | hai lon coca | type + top1 | INV digit ↔ word qty |
| INV-04 | C-ALIAS | G1-02 | coke | Coca | type | INV-3 case-fold |
| INV-05 | C-VAR | G5-06 | pepsi không zero không light | pepsi không light không zero | type + top1 | must_not order invariant |
| INV-06 | C-CAT | G4-01 | nước mắm | tôi cần mua nước mắm | type + top1 | INV-1 filler trên category |
| INV-07 | C-SPEC | G3-05 | 1 thùng coca | thùng coca cho tôi nhé | type + top1 | filler + reorder trên C-SPEC |
| INV-08 | C-TRAP | G6-01 | trà bí đao coca la hán quả | trà bí đao có vị coca la hán | type + top1 | brand FUZETEA giữ nguyên |
| INV-09 | C-ABST | G7-01 | bia không cồn | bia không có cồn | type | Paraphrase "không cồn" = "không có cồn" — cả hai phải no_result |

---

## DIR cases — Directional expectation (8)

> Mỗi case có `Query A → Query B` và một **directional rule**: output B phải thay đổi đúng
> chiều quy định so với A. Vi phạm = FAIL.

| ID | Cap | Query A | Query B | Directional rule | Notes |
|---|---|---|---|---|---|
| DIR-01 | C-BRAND | coca lon | coca chai | items[*].packaging chuyển từ "lon" → "chai" trên ≥1 item | DIR-1 packaging |
| DIR-02 | C-VAR | coca | coca thường | items B không chứa "light"/"zero"/"không đường" (A có thể chứa) | DIR-2 variant exclude |
| DIR-03 | C-BRAND | coca lon | pepsi lon | items B chứa brand "pepsi", không chứa "coca" | DIR-3 brand swap |
| DIR-04 | C-SPEC | coca 330ml | coca 1.5l | items B size_value ≈ 1500, không phải 330 | size change |
| DIR-05 | C-VAR | coca | coca zero | items B chứa "zero"/"không đường"; A không bắt buộc | variant add |
| DIR-06 | C-ABST | coca | coca không cồn | type B = no_result (variant OOC) | abstain on OOC variant |
| DIR-07 | C-CAT | bia | bia lon | items B chỉ chứa packaging "lon" trên top-3 | packaging narrow |
| DIR-08 | C-SPEC | vinamilk | vinamilk hộp nhỏ | items B có size_hint nhỏ, packaging "hộp" | size narrow |
| DIR-09 | C-TRAP | trà xanh 0 độ | bia 0 độ | type B phải là no_result | Đổi category trà→bia trên "0 độ" — bia 0 độ là bia không cồn, OOC |

---

## Coverage matrix (capability × test type)

| Cap | MFT | INV | DIR | Tổng |
|---|---|---|---|---|
| C-ALIAS | 6 | 1 | 0 | 7 |
| C-BRAND | 9 | 1 | 2 | 12 |
| C-SPEC | 8 | 1 | 2 | 11 |
| C-CAT | 6 | 1 | 1 | 8 |
| C-VAR | 7 | 1 | 2 | 10 |
| C-TRAP | 4 | 2 | 1 | 7 |
| C-ABST | 6 | 1 | 1 | 8 |
| C-NL | 8 | 2 | 0 | 10 |
| **Tổng** | **54** | **10** | **9** | **73** |

> Sàn coverage theo [eval-goal §7.1](../docs/eval-goal.md#71-dev-set-public): mỗi capability ≥ 8 case,
> mỗi (capability × test type) ≥ 1. C-TRAP và C-ABST đã có đủ INV+DIR.
> **Còn thiếu 7 case để đạt 80** — bổ sung trước gate-check đầu tiên bằng cách thêm MFT vào C-ALIAS, C-TRAP, C-ABST.

---

## TODO trước gate-check đầu tiên

1. **Điền `Top1`** cho mọi MFT có `In-Cat=true` — query ES sau reindex để lấy ID kỳ vọng.
2. **Bổ sung C-TRAP INV-pair thứ 2 + DIR-pair đầu tiên** (vd `"trà 0 độ"` → `"trà xanh 0 độ"`).
3. **Bổ sung C-ABST INV-pair** (vd `"thuốc cảm"` ≡ `"cho tôi mua thuốc cảm"` — cả hai phải no_result).
4. **Soạn blind set** 60 case ở `tests/blind/` theo cùng schema, niêm phong (xem [eval-goal §7.2](../docs/eval-goal.md#72-blind-set-sealed)).

Không tự thêm/bớt case để cải thiện điểm. Sửa case = sửa contract (xem
[eval-goal §8](../docs/eval-goal.md#8-anti-gaming-rules)).
