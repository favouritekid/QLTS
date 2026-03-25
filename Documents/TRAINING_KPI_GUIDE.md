# Hướng dẫn KPI — Hệ thống Quản lý Tuyển sinh (QLTS)

> Tài liệu training cho nhân viên tư vấn tuyển sinh
> Cập nhật: 2026-03-25

---

## Mục lục

1. [Tổng quan: Hệ thống đo lường hiệu quả](#1-tổng-quan)
2. [Quy trình tuyển sinh trên hệ thống](#2-quy-trình-tuyển-sinh)
3. [Các chỉ số KPI chính](#3-các-chỉ-số-kpi-chính)
4. [Chỉ số chất lượng hàng ngày](#4-chỉ-số-chất-lượng-hàng-ngày)
5. [Biểu đồ phễu tuyển sinh](#5-biểu-đồ-phễu-tuyển-sinh)
6. [Cách xem dashboard](#6-cách-xem-dashboard)
7. [Mục tiêu (Target) và cách hệ thống gán](#7-mục-tiêu-target)
8. [Mẹo để đạt target](#8-mẹo-để-đạt-target)
9. [Lỗi phổ biến của nhân viên mới](#9-lỗi-phổ-biến-của-nhân-viên-mới)
10. [Câu hỏi thường gặp](#10-câu-hỏi-thường-gặp)

---

## 1. Tổng quan

Hệ thống QLTS theo dõi hiệu quả công việc của tư vấn viên thông qua **8 chỉ số KPI chính** và **5 chỉ số chất lượng hàng ngày**. Tất cả được hiển thị trên **Dashboard** — trang tổng quan cá nhân mà bạn thấy khi đăng nhập.

### Dashboard gồm những gì?

| Khu vực | Nội dung |
|---------|----------|
| **Thẻ KPI chính** (hàng trên) | Tư vấn hôm nay, Leads đang xử lý, Tỉ lệ chốt đơn, Chuyển đổi lead mới |
| **Thẻ KPI phụ** (dải giữa) | Tuân thủ SLA, Hiệu quả tư vấn, Thời gian phản hồi, Nhập học |
| **Chỉ số chất lượng** (bên dưới) | TV hợp lệ, Tỷ lệ chất lượng, Cam kết follow-up, D+7, D+3 |
| **Biểu đồ phễu** | Phân bố leads theo từng giai đoạn tuyển sinh |
| **Biểu đồ xu hướng** | Số leads tư vấn, phân công, chuyển đổi theo ngày |
| **Chỉ tiêu năm** | Tiến độ nhập học so với chỉ tiêu năm |

### Quy ước màu sắc trên dashboard

| Màu / Biểu tượng | Ý nghĩa |
|-------------------|---------|
| **Xanh lá** | Đạt hoặc vượt target |
| **Vàng** | Gần target (≥80% nhưng chưa đạt) |
| **Đỏ** | Chưa đạt target (<80%) |
| **Mũi tên ↑ xanh** | Cải thiện so với kỳ trước |
| **Mũi tên ↓ đỏ** | Giảm so với kỳ trước |
| **Mũi tên → xám** | Không thay đổi / chưa có dữ liệu |
| **⚠ Cảnh báo** | Bottleneck — giai đoạn cần chú ý |

### Hệ thống đếm như thế nào?

- **Chỉ đếm tư vấn thật** — các tư vấn tự động do hệ thống tạo (ví dụ khi chuyển trạng thái hồ sơ) KHÔNG được tính vào KPI
- **Ngày tính theo giờ Việt Nam** — "hôm nay" là từ 00:00 đến 23:59 giờ VN, không phải giờ UTC
- **Leads đã xóa không tính** — chỉ leads đang hoạt động mới ảnh hưởng KPI

---

## 2. Quy trình tuyển sinh

Mỗi lead (học viên tiềm năng) đi qua các giai đoạn sau:

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ Chưa     │ →  │ Đang     │ →  │ Đã nộp   │ →  │ Kết quả  │ →  │ Xử lý   │ →  │ Đã nhập  │
│ tư vấn   │    │ tư vấn   │    │ hồ sơ    │    │ hồ sơ    │    │ học phí  │    │ học ✓    │
└──────────┘    └────┬─────┘    └──────────┘    └────┬─────┘    └──────────┘    └──────────┘
                     │                               │
                     └───────── Không đi học ✗ ←─────┘
```

### Trạng thái tư vấn chi tiết

| Giai đoạn | Trạng thái | Ý nghĩa |
|-----------|-----------|---------|
| **Chưa tư vấn** | Chưa tiếp cận | Lead mới, chưa liên hệ |
| | Đã kết nối liên hệ | Đã gọi/nhắn, chờ phản hồi |
| **Đang tư vấn** | Có nhu cầu tìm hiểu | Lead quan tâm, đang tìm hiểu |
| | Đồng ý tư vấn | Lead đồng ý nhận tư vấn chi tiết |
| | Hẹn liên hệ lại | Đã hẹn lịch gọi lại |
| | Từ chối tư vấn | Lead từ chối (xem hướng xử lý bên dưới) |
| **Đã nộp hồ sơ** | Đã tiếp nhận hồ sơ | Hồ sơ đã gửi |
| | Đã hoàn tất lệ phí xét tuyển | Đã đóng phí xét tuyển |
| | Yêu cầu bổ sung hồ sơ | Cần bổ sung giấy tờ |
| **Kết quả hồ sơ** | Đủ điều kiện nhập học | Hồ sơ đạt yêu cầu |
| | Hồ sơ không đạt yêu cầu | Hồ sơ bị từ chối (**kết thúc**) |
| **Xử lý học phí** | Chưa hoàn tất học phí | Đang chờ đóng học phí |
| | Đã hoàn tất học phí | Đã đóng đủ học phí |
| | Đã hoàn học phí | Hoàn thành (**kết thúc**) |
| **Kết quả cuối** | Đã xác nhận nhập học | Thành công (**kết thúc**) |
| | Không tiếp tục hồ sơ | Thất bại (**kết thúc**) |
| | Ngừng theo học | Thất bại (**kết thúc**) |

### Trạng thái hoạt động (dùng ở mọi giai đoạn)

Đây là các trạng thái ghi nhận hoạt động liên hệ, **không** làm thay đổi giai đoạn của lead:

| Trạng thái | Khi nào dùng |
|-----------|-------------|
| Không nghe máy | Gọi nhưng không nghe |
| Nhắn tin không phản hồi | Nhắn tin nhưng chưa trả lời |
| Đã hủy lịch hẹn | Lead hủy lịch hẹn tư vấn |

**Lưu ý:** Các trạng thái hoạt động không hiển thị trong biểu đồ phễu, nhưng lead vẫn được tính là "đang xử lý" trên thẻ KPI.

### Xử lý lead "Từ chối tư vấn"

Lead ở trạng thái "Từ chối tư vấn" vẫn nằm trong giai đoạn "Đang tư vấn" — chưa kết thúc. Hướng xử lý:

- **Trong 1-2 tuần đầu:** Thử liên hệ lại 1-2 lần, có thể lead thay đổi ý định
- **Sau 2 tuần không phản hồi:** Trao đổi với quản lý để xem xét chuyển sang "Không đi học" (kết thúc)
- **Nếu từ chối rõ ràng:** Ghi nhận loss reason (lý do mất) rồi chuyển sang trạng thái kết thúc

Đừng giữ lead "Từ chối tư vấn" quá lâu — nó ảnh hưởng đến Win Rate và Hiệu quả tư vấn.

---

## 3. Các chỉ số KPI chính

### 3.1. Tư vấn hôm nay / Trung bình tư vấn ngày

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Số lần tư vấn bạn thực hiện trong ngày (hoặc trung bình/ngày nếu xem khoảng thời gian quá khứ) |
| **Cách tính** | Đếm số consultation do bạn tạo, loại bỏ tư vấn tự động của hệ thống |
| **Mục tiêu mặc định** | **10 tư vấn/ngày** |
| **Càng cao càng tốt** | Có |

**Ví dụ:** Bạn gọi điện tư vấn cho 8 học viên tiềm năng trong ngày → KPI = 8/10

### 3.2. Leads đang xử lý

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Tổng số leads đang được bạn phụ trách và chưa kết thúc |
| **Cách tính** | Đếm tất cả leads gán cho bạn mà trạng thái chưa phải "kết thúc" (chưa nhập học hoặc chưa mất) |
| **Mục tiêu** | Không có target cố định — đây là số liệu thực tế phản ánh khối lượng công việc |

**Ví dụ:** Bạn đang phụ trách 45 leads ở các giai đoạn khác nhau → hiển thị 45

### 3.3. Tỉ lệ chốt đơn (Win Rate)

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Trong số leads đã kết thúc, bao nhiêu % kết thúc thành công (nhập học)? |
| **Cách tính** | `Số leads thắng / (Số leads thắng + Số leads thua) × 100` |
| **Mục tiêu mặc định** | **33%** (cứ 3 leads kết thúc thì 1 lead nhập học) |
| **Càng cao càng tốt** | Có |

**Ví dụ:** Trong tháng, 10 leads kết thúc: 4 nhập học, 6 mất → Win Rate = 4/10 = 40%

### 3.4. Chuyển đổi lead mới

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Trong số leads MỚI được giao cho bạn trong kỳ, bao nhiêu % đã chuyển đổi thành công? |
| **Cách tính** | `Leads mới đã chuyển đổi / Tổng leads mới được giao × 100` |
| **Mục tiêu mặc định** | **15%** |
| **Càng cao càng tốt** | Có |

**Lưu ý:** Đây là chỉ số xu hướng — hệ thống hiển thị để bạn theo dõi, không so sánh trực tiếp với target trên dashboard.

### 3.5. Thời gian phản hồi

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Trung bình bạn mất bao lâu từ khi được giao lead đến lần tư vấn đầu tiên? |
| **Cách tính** | `Trung bình (thời điểm tư vấn đầu tiên − thời điểm được giao lead)` |
| **Mục tiêu mặc định** | **≤ 2 giờ** |
| **Càng THẤP càng tốt** | Có — phản hồi nhanh = tốt |

**Ví dụ:** Bạn được giao lead lúc 9:00, gọi tư vấn lúc 10:30 → thời gian phản hồi = 1.5 giờ (đạt SLA)

### 3.6. Tuân thủ SLA

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Bao nhiêu % leads bạn phản hồi đúng hạn (trong vòng 2 giờ)? |
| **Mục tiêu mặc định** | **80%** |
| **Càng cao càng tốt** | Có |

**Cách tính chi tiết:**

```
                    Leads phản hồi trong 2 giờ
SLA (%) = ─────────────────────────────────────────────── × 100
          Leads đã phản hồi + Leads quá hạn chưa phản hồi
```

Mẫu số gồm **hai nhóm**:
1. **Leads đã phản hồi** (dù đúng hạn hay trễ) — tất cả leads bạn đã tư vấn ít nhất 1 lần
2. **Leads quá hạn chưa phản hồi** — leads được giao **hơn 2 giờ trước** mà bạn **chưa liên hệ lần nào**

Leads mới giao **chưa đến 2 giờ** và chưa liên hệ → **chưa bị tính** (vẫn trong thời hạn SLA).

**Ví dụ thực tế trên hệ thống:**
- 57 leads đã được tư vấn ít nhất 1 lần, trong đó 16 leads phản hồi trong 2 giờ
- 9 leads chưa tư vấn lần nào và đã quá hạn 2 giờ
- Mẫu số = 57 + 9 = 66
- **SLA = 16 / 66 = 24.2%**

### 3.7. Hiệu quả tư vấn

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Trong số leads bạn đã tư vấn VÀ đã kết thúc, bao nhiêu % thành công? |
| **Mục tiêu mặc định** | **50%** |
| **Càng cao càng tốt** | Có |

**Cách tính:**

```
                   (Leads đã tư vấn) VÀ (kết thúc thắng)
Hiệu quả (%) = ──────────────────────────────────────────── × 100
                (Leads đã tư vấn) VÀ (kết thúc thắng + thua)
```

Tử số: leads mà bạn đã tư vấn ít nhất 1 lần **VÀ** kết thúc thành công (nhập học).
Mẫu số: leads mà bạn đã tư vấn ít nhất 1 lần **VÀ** kết thúc (bất kỳ — thắng hoặc thua).

**Khác với Win Rate:** Win Rate tính **tất cả** leads kết thúc (kể cả leads bạn chưa tư vấn lần nào). Hiệu quả tư vấn chỉ tính leads mà bạn **đã tư vấn ít nhất 1 lần** — đo chất lượng tư vấn của bạn.

### 3.8. Nhập học (tháng)

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Số leads đã nhập học thành công trong tháng |
| **Cách tính** | Đếm leads đạt trạng thái "Đã xác nhận nhập học" trong kỳ |
| **Mục tiêu mặc định** | **7 leads/tháng** |
| **Càng cao càng tốt** | Có |

---

## 4. Chỉ số chất lượng hàng ngày

Đây là các chỉ số **theo thời gian thực**, chỉ hiển thị khi bạn xem dashboard cá nhân. Chúng đo **chất lượng** công việc hàng ngày, không chỉ số lượng.

| # | Chỉ số | Ngưỡng tham chiếu | Ý nghĩa |
|---|--------|-------------------|---------|
| D1 | **TV hợp lệ** | Nên ≥ 70% tổng TV | Tư vấn có cập nhật trạng thái |
| D2 | **Tỷ lệ chất lượng** | Nên ≥ 70% | TV hợp lệ / Tổng TV |
| D3 | **Cam kết follow-up** | Nên ≥ 80% | % TV có đặt lịch hẹn tiếp |
| D4 | **Tiến triển D+7** | Nên ≥ 30% | % leads tiến giai đoạn sau 7 ngày |
| D5 | **Tụt hạng D+3** | Nên ≤ 10% | % leads tụt giai đoạn sau 3 ngày |

### 4.1. TV hợp lệ (Verified Consultations)

Số leads bạn tư vấn hôm nay mà có thay đổi trạng thái thực sự trên hệ thống. Một tư vấn "hợp lệ" là khi bạn tư vấn **VÀ** cập nhật trạng thái lead.

**Ví dụ:** Bạn tư vấn 10 leads, 7 leads bạn cập nhật trạng thái → TV hợp lệ = 7

### 4.2. Tỷ lệ chất lượng

```
Tỷ lệ chất lượng = TV hợp lệ / Tổng tư vấn hôm nay × 100
```

**Ví dụ:** 7 TV hợp lệ / 10 tổng TV = **70%** → Đạt ngưỡng tham chiếu

### 4.3. Cam kết follow-up

Trong số TV hợp lệ cho leads chưa kết thúc, bao nhiêu % có đặt lịch hẹn tiếp?

**Tại sao quan trọng:** Follow-up đều đặn giúp leads không "nguội". Leads không được follow-up thường tụt giai đoạn hoặc mất.

### 4.4. Tiến triển D+7

Leads bạn tư vấn **7 ngày trước** — bao nhiêu % đã tiến lên giai đoạn tiếp?

**Tại sao quan trọng:** Đo hiệu quả dài hạn — tư vấn tuần trước có tạo ra kết quả thực sự không? Nếu tỷ lệ thấp, có thể cách tư vấn cần cải thiện.

### 4.5. Tụt hạng D+3

Leads bạn tư vấn **3 ngày trước** — bao nhiêu % bị tụt về giai đoạn trước?

**Càng THẤP càng tốt** — 0% là lý tưởng. Nếu tỷ lệ cao, kiểm tra xem leads có đang bị chuyển trạng thái sai hoặc không được chăm sóc kịp thời.

---

## 5. Biểu đồ phễu tuyển sinh

Biểu đồ phễu cho thấy leads **đang xử lý** phân bố ở đâu trong quy trình. Phễu **chỉ hiển thị leads chưa kết thúc** — leads đã nhập học hoặc đã mất không nằm trong phễu.

```
 ┌──────────────────────────────────────────────────────┐
 │              Chưa tư vấn: 20 leads (30%)             │  ← Cần liên hệ
 ├─────────────────────────────────────────────┤
 │            Đang tư vấn: 45 leads (68%)      │  ← Đang xử lý
 ├────────────────────────┤
 │   Đã nộp hồ sơ: 1 (2%) │
 ├──────────┤                                             ┌──────────────┐
 │  Kết quả │                                             │ Đã nhập học: │
 ├──────┤                                                 │    0 leads   │
 │Học phí│                                                │ Không đi học:│
 └──────┘                                                 │    0 leads   │
   Leads đang xử lý: 66                                  └──────────────┘
                                                           Leads kết thúc
```

### Đọc phễu thế nào?

- **Thanh rộng nhất** = giai đoạn có nhiều leads nhất → đây là nơi bạn cần tập trung
- **Click vào bất kỳ thanh nào** → xem danh sách leads chi tiết tại giai đoạn đó
- **% bên cạnh** = tỷ lệ leads ở giai đoạn này so với tổng toàn bộ leads (đang xử lý + kết thúc)
- **⚠ Bottleneck** (biểu tượng cảnh báo) = giai đoạn có tỷ lệ chuyển đổi thấp nhất → cần tập trung cải thiện

**Lưu ý:** Tổng trên phễu có thể khác con số "Leads đang xử lý" nếu có leads ở trạng thái hoạt động (Không nghe máy, Nhắn tin không phản hồi, Hủy hẹn) — các trạng thái này tính là "đang xử lý" nhưng không hiển thị trên phễu.

---

## 6. Cách xem dashboard

### Chọn kỳ (date range)

Ở góc trên bên phải dashboard có bộ chọn ngày:

| Thao tác | Kết quả |
|----------|---------|
| **Mặc định** | 7 ngày gần nhất |
| **Chọn "Tháng này"** | Từ ngày 1 đến hôm nay của tháng hiện tại |
| **Chọn ngày cụ thể** | Click vào lịch, chọn ngày bắt đầu → ngày kết thúc |
| **Chọn "Hôm nay"** | Chỉ xem dữ liệu hôm nay |

### Kỳ ảnh hưởng gì?

| KPI | Kỳ mặc định 7 ngày | Kỳ theo tháng |
|-----|---------------------|---------------|
| Tư vấn | Hiện **trung bình/ngày** | Hiện **trung bình/ngày** |
| Tư vấn (nếu hôm nay nằm trong kỳ) | Hiện **số hôm nay / target** | Hiện **số hôm nay / target** |
| Win Rate | Hiện % nhưng **không** so target | Hiện % **có** so target |
| Nhập học | Hiện số nhưng **không** so target | Hiện số **có** so target |
| SLA, Phản hồi | Luôn hiện + so target | Luôn hiện + so target |
| Leads đang xử lý | **Không** phụ thuộc kỳ (realtime) | **Không** phụ thuộc kỳ |

**Mẹo:** Muốn so sánh với target chính xác, chọn kỳ theo **tháng** (ví dụ: 01/03 → 31/03).

### Xu hướng (trend arrows)

Mũi tên bên cạnh mỗi KPI so sánh kỳ hiện tại với **cùng khoảng thời gian ngay trước đó**:
- Xem 7 ngày (18-24/3) → so với 7 ngày trước (11-17/3)
- Xem tháng 3 → so với tháng 2

---

## 7. Mục tiêu (Target)

### Hệ thống gán target theo thứ tự ưu tiên

```
1. Target riêng cho BẠN (nếu quản lý đã gán)
   ↓ không có?
2. Target của đơn vị bạn thuộc
   ↓ không có?
3. Target toàn trường
   ↓ không có?
4. Giá trị mặc định của hệ thống
```

Nếu dashboard hiện dòng nhỏ "Target đơn vị" bên cạnh mục tiêu, nghĩa là bạn đang dùng target của đơn vị, chưa có target riêng.

### Bảng target mặc định

| KPI | Target | Đơn vị |
|-----|--------|--------|
| Tư vấn/ngày | 10 | lần/ngày |
| Tỉ lệ chốt đơn | 33% | % |
| Chuyển đổi lead mới | 15% | % |
| Thời gian phản hồi | ≤ 2 | giờ |
| Tuân thủ SLA | 80% | % |
| Hiệu quả tư vấn | 50% | % |
| Nhập học/tháng | 7 | leads/tháng |
| Nhập học/năm | 80 | leads/năm |

---

## 8. Mẹo để đạt target

### Tư vấn hôm nay: đạt 10 tư vấn/ngày

- Lên lịch cố định: sáng 5 cuộc, chiều 5 cuộc
- Ưu tiên leads mới được giao trước (giúp đạt SLA luôn)
- Ghi chú kết quả ngay sau mỗi cuộc gọi → hệ thống đếm chính xác
- Dùng trạng thái "Hẹn liên hệ lại" nếu chưa liên lạc được → hẹn lịch follow-up

### Thời gian phản hồi & SLA: phản hồi trong 2 giờ

- **Kiểm tra leads mới ngay đầu giờ làm việc** — leads giao ngoài giờ vẫn tính SLA
- Leads mới giao → gọi ngay, dù chỉ để giới thiệu ngắn
- Nếu không gọi được → nhắn tin / email ngay → vẫn tính là phản hồi
- Đặt thông báo (notification) cho leads mới được giao

### Tỉ lệ chốt đơn: đạt 33%

- Tập trung vào leads có điểm cao (hot lead) — hệ thống chấm điểm tự động
- Leads "Từ chối tư vấn" quá 2 tuần → trao đổi quản lý để kết thúc, tránh kéo dài
- Giải quyết lo ngại của học viên: học phí, thời điểm chưa phù hợp
- Follow-up đều đặn — leads hẹn lại cần được liên hệ đúng hẹn

### Hiệu quả tư vấn: đạt 50%

- Chuẩn bị trước khi gọi: xem hồ sơ lead, ngành quan tâm, điểm số
- Tư vấn đúng ngành phù hợp với lead → tăng tỷ lệ chuyển đổi
- Ghi nhận lý do mất leads (loss reason) → rút kinh nghiệm cho leads sau
- Nếu lead không phù hợp → chuyển sớm, đừng kéo dài → giữ tỷ lệ hiệu quả

### Nhập học: đạt 7 leads/tháng

- Theo sát leads đã nộp hồ sơ → đẩy nhanh qua giai đoạn xét tuyển
- Hỗ trợ leads hoàn tất giấy tờ → giảm thời gian chờ
- Nhắc nhở leads đóng học phí đúng hạn
- Mỗi tuần review leads ở giai đoạn "Xử lý học phí" → push kết thúc

### Chỉ số chất lượng hàng ngày

- **Luôn cập nhật trạng thái** sau mỗi cuộc tư vấn → tăng TV hợp lệ (mục tiêu ≥70%)
- **Đặt lịch hẹn tiếp** cho leads chưa kết thúc → tăng cam kết follow-up (mục tiêu ≥80%)
- **Xem D+7 và D+3** mỗi sáng → biết leads nào cần chú ý đặc biệt
- D+7 dưới 30% → xem lại cách tư vấn, có thể cần thay đổi cách tiếp cận
- D+3 trên 10% → leads đang bị "nguội", cần follow-up tích cực hơn

---

## 9. Lỗi phổ biến của nhân viên mới

### Lỗi 1: Gọi điện nhưng quên ghi consultation trên hệ thống

**Hậu quả:** KPI "Tư vấn hôm nay" = 0 dù bạn đã gọi 10 cuộc. SLA cũng bị ảnh hưởng vì hệ thống không biết bạn đã liên hệ.

**Cách tránh:** Sau MỖI cuộc gọi, vào lead trên hệ thống → Thêm tư vấn → Ghi kết quả.

### Lỗi 2: Nhầm trạng thái hoạt động với trạng thái pipeline

**Hậu quả:** Chọn "Không nghe máy" (trạng thái hoạt động) khi đáng lẽ phải chọn "Đã kết nối liên hệ" (trạng thái pipeline). Lead không tiến giai đoạn → phễu bị lệch.

**Cách phân biệt:**
- **Trạng thái pipeline** (có stage): thay đổi vị trí lead trên phễu
- **Trạng thái hoạt động** (không có stage): chỉ ghi nhận hành động, lead giữ nguyên vị trí

### Lỗi 3: Không cập nhật trạng thái sau tư vấn

**Hậu quả:** "TV hợp lệ" thấp, "Tỷ lệ chất lượng" giảm. Lead vẫn ở trạng thái cũ trên phễu.

**Cách tránh:** Khi thêm consultation, luôn chọn trạng thái mới phù hợp (ví dụ: "Có nhu cầu tìm hiểu" → "Đồng ý tư vấn").

### Lỗi 4: Giữ leads "chết" quá lâu

**Hậu quả:** Số "Leads đang xử lý" cao nhưng thực chất nhiều leads không còn tiềm năng → Win Rate và Hiệu quả bị kéo xuống khi kết thúc.

**Cách tránh:** Review danh sách leads mỗi tuần. Leads không phản hồi sau 3 lần liên hệ → trao đổi quản lý để kết thúc.

### Lỗi 5: Chỉ nhìn số lượng, bỏ qua chất lượng

**Hậu quả:** Tư vấn 15 cuộc/ngày (vượt target) nhưng không cập nhật trạng thái, không đặt follow-up → D1-D5 thấp.

**Cách tránh:** Xem cả **hàng trên** (số lượng) lẫn **hàng dưới** (chất lượng) trên dashboard mỗi cuối ngày.

---

## 10. Câu hỏi thường gặp

### "Tại sao tư vấn của tôi không được đếm?"

Kiểm tra:
- Bạn có tạo consultation trên hệ thống không? (không chỉ gọi điện mà phải ghi nhận)
- Consultation có phải do hệ thống tự tạo (method=system) không? → không tính
- Consultation có bị xóa không?

### "Tại sao SLA của tôi thấp?"

SLA đếm cả leads bạn **chưa liên hệ** mà đã quá 2 giờ. Chỉ cần 9 leads chưa gọi + quá hạn → tất cả đều bị tính vi phạm, kéo SLA xuống rất nhanh.

**Giải pháp:** Liên hệ leads mới ngay khi được giao, ít nhất gọi 1 cuộc dù ngắn.

### "Win Rate 0% nhưng tôi đang làm tốt mà?"

Win Rate chỉ tính leads **đã kết thúc** (nhập học hoặc mất). Nếu chưa có lead nào kết thúc trong kỳ → Win Rate = 0% (không có đủ dữ liệu, không phải bạn làm kém).

### "Số trên phễu không bằng Leads đang xử lý?"

Phễu chỉ đếm leads có trạng thái tư vấn **thuộc phễu**. Một số trạng thái hoạt động (Không nghe máy, Nhắn tin không phản hồi, Hủy hẹn) không hiển thị trong phễu nhưng vẫn tính là "đang xử lý". Chênh lệch nhỏ (1-5 leads) là bình thường.

### "Thời gian phản hồi tính từ lúc nào?"

Từ lúc **lead được giao cho bạn** (assigned_at) đến lần tư vấn **đầu tiên** bạn thực hiện. Nếu lead được giao lúc 8:00 sáng và bạn gọi lúc 2:00 chiều → 6 giờ.

### "Mũi tên xu hướng so sánh với gì?"

So sánh với **cùng khoảng thời gian trước đó**. Ví dụ: nếu bạn đang xem 7 ngày gần nhất (18-24/3), hệ thống so với 7 ngày trước đó (11-17/3).

### "Tôi có thể xem KPI của người khác không?"

- **Tư vấn viên**: chỉ xem được dashboard cá nhân
- **Quản lý**: xem được dashboard đơn vị (tất cả tư vấn viên trong đơn vị)
- **Admin**: xem được toàn bộ tổ chức + drill-down vào từng tư vấn viên

### "Chỉ số chất lượng hàng ngày tốt/xấu thế nào?"

| Chỉ số | Tốt | Trung bình | Cần cải thiện |
|--------|-----|-----------|---------------|
| Tỷ lệ chất lượng | ≥80% | 60-79% | <60% |
| Cam kết follow-up | ≥80% | 60-79% | <60% |
| Tiến triển D+7 | ≥40% | 20-39% | <20% |
| Tụt hạng D+3 | ≤5% | 6-15% | >15% |

---

## Phụ lục: Bảng tóm tắt KPI

| # | KPI | Mục tiêu | Đơn vị | Hướng tốt | Cách cải thiện nhanh nhất |
|---|-----|----------|--------|-----------|--------------------------|
| 1 | Tư vấn/ngày | 10 | lần | Cao | Lên lịch gọi cố định sáng + chiều |
| 2 | Tỉ lệ chốt | 33% | % | Cao | Tập trung leads tiềm năng, giải quyết objections |
| 3 | Chuyển đổi mới | 15% | % | Cao | Chất lượng > số lượng, match đúng ngành |
| 4 | Phản hồi | ≤2h | giờ | Thấp | Gọi ngay khi được giao lead |
| 5 | SLA | 80% | % | Cao | Không để lead chờ quá 2 giờ |
| 6 | Hiệu quả TV | 50% | % | Cao | Chuẩn bị kỹ trước khi tư vấn |
| 7 | Nhập học/tháng | 7 | leads | Cao | Đẩy nhanh hồ sơ + học phí |
| 8 | Nhập học/năm | 80 | leads | Cao | Duy trì đều đặn qua các tháng |
