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
6. [Mục tiêu (Target) và cách hệ thống gán](#6-mục-tiêu-target)
7. [Mẹo để đạt target](#7-mẹo-để-đạt-target)
8. [Câu hỏi thường gặp](#8-câu-hỏi-thường-gặp)

---

## 1. Tổng quan

Hệ thống QLTS theo dõi hiệu quả công việc của tư vấn viên thông qua **8 chỉ số KPI chính** và **5 chỉ số chất lượng hàng ngày**. Tất cả được hiển thị trên **Dashboard** — trang tổng quan cá nhân mà bạn thấy khi đăng nhập.

### Dashboard gồm những gì?

| Khu vực | Nội dung |
|---------|----------|
| **Thẻ KPI chính** (hàng trên) | Tư vấn hôm nay, Leads đang xử lý, Tỉ lệ chốt đơn, Chuyển đổi lead mới |
| **Thẻ KPI phụ** (dải giữa) | Tuân thủ SLA, Hiệu quả tư vấn, Thời gian phản hồi, Nhập học |
| **Biểu đồ phễu** | Phân bố leads theo từng giai đoạn tuyển sinh |
| **Biểu đồ xu hướng** | Số leads tư vấn, phân công, chuyển đổi theo ngày |
| **Chỉ tiêu năm** | Tiến độ nhập học so với chỉ tiêu năm |

### Hệ thống đếm như thế nào?

- **Chỉ đếm tư vấn thật** — các tư vấn tự động do hệ thống tạo (ví dụ khi chuyển trạng thái hồ sơ) KHÔNG được tính vào KPI
- **Ngày tính theo giờ Việt Nam** — "hôm nay" là từ 00:00 đến 23:59 giờ VN, không phải giờ UTC
- **Leads đã xóa không tính** — chỉ leads đang hoạt động mới ảnh hưởng KPI

---

## 2. Quy trình tuyển sinh

Mỗi lead (học viên tiềm năng) đi qua các giai đoạn sau:

```
Chưa tư vấn → Đang tư vấn → Đã nộp hồ sơ → Kết quả hồ sơ → Xử lý học phí → Đã nhập học
                    ↓                                                              ↑
              Không đi học ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←
```

### Trạng thái tư vấn chi tiết

| Giai đoạn | Trạng thái | Ý nghĩa |
|-----------|-----------|---------|
| **Chưa tư vấn** | Chưa tiếp cận | Lead mới, chưa liên hệ |
| | Đã kết nối liên hệ | Đã gọi/nhắn, chờ phản hồi |
| **Đang tư vấn** | Có nhu cầu tìm hiểu | Lead quan tâm, đang tìm hiểu |
| | Đồng ý tư vấn | Lead đồng ý nhận tư vấn chi tiết |
| | Hẹn liên hệ lại | Đã hẹn lịch gọi lại |
| | Từ chối tư vấn | Lead từ chối (nhưng chưa đóng hồ sơ) |
| **Đã nộp hồ sơ** | Đã tiếp nhận hồ sơ | Hồ sơ đã gửi |
| | Đã hoàn tất lệ phí xét tuyển | Đã đóng phí xét tuyển |
| | Yêu cầu bổ sung hồ sơ | Cần bổ sung giấy tờ |
| **Kết quả hồ sơ** | Đủ điều kiện nhập học | Hồ sơ đạt yêu cầu |
| | Hồ sơ không đạt yêu cầu | Hồ sơ bị từ chối (kết thúc) |
| **Xử lý học phí** | Chưa hoàn tất học phí | Đang chờ đóng học phí |
| | Đã hoàn tất học phí | Đã đóng đủ học phí |
| | Đã hoàn học phí | Hoàn thành (kết thúc) |
| **Kết quả cuối** | Đã xác nhận nhập học | Thành công (kết thúc) |
| | Không tiếp tục hồ sơ | Thất bại (kết thúc) |
| | Ngừng theo học | Thất bại (kết thúc) |

### Trạng thái hoạt động (dùng ở mọi giai đoạn)

Đây là các trạng thái ghi nhận hoạt động liên hệ, **không** làm thay đổi giai đoạn của lead:

| Trạng thái | Khi nào dùng |
|-----------|-------------|
| Không nghe máy | Gọi nhưng không nghe |
| Nhắn tin không phản hồi | Nhắn tin nhưng chưa trả lời |
| Đã hủy lịch hẹn | Lead hủy lịch hẹn tư vấn |

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
| **Cách tính** | `Leads phản hồi đúng hạn / (Leads đã phản hồi + Leads quá hạn chưa phản hồi) × 100` |
| **Mục tiêu mặc định** | **80%** |
| **Càng cao càng tốt** | Có |

**Chi tiết quan trọng:**
- Lead được giao cho bạn **quá 2 giờ** mà bạn **chưa liên hệ lần nào** → tính là vi phạm SLA
- Lead bạn liên hệ **trong vòng 2 giờ** sau khi được giao → đạt SLA
- Lead bạn liên hệ **sau 2 giờ** → không đạt SLA nhưng ít nhất đã phản hồi

**Ví dụ:** Bạn được giao 66 leads trong tuần:
- 16 leads bạn phản hồi trong 2 giờ (compliant)
- 41 leads bạn phản hồi nhưng trễ hơn 2 giờ
- 9 leads bạn chưa liên hệ và đã quá 2 giờ (overdue)
- SLA = 16 / 66 = **24.2%**

### 3.7. Hiệu quả tư vấn

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Trong số leads bạn đã tư vấn VÀ đã kết thúc, bao nhiêu % thành công? |
| **Cách tính** | `Leads đã tư vấn + kết thúc thắng / Leads đã tư vấn + kết thúc (thắng + thua) × 100` |
| **Mục tiêu mặc định** | **50%** |
| **Càng cao càng tốt** | Có |

**Khác với Win Rate:** Win Rate tính tất cả leads kết thúc. Hiệu quả tư vấn chỉ tính leads mà bạn **đã tư vấn ít nhất 1 lần**.

### 3.8. Nhập học (tháng)

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Số leads đã nhập học thành công trong tháng |
| **Cách tính** | Đếm leads đạt trạng thái "Đã xác nhận nhập học" trong kỳ |
| **Mục tiêu mặc định** | **7 leads/tháng** |
| **Càng cao càng tốt** | Có |

---

## 4. Chỉ số chất lượng hàng ngày

Đây là các chỉ số **theo thời gian thực**, chỉ hiển thị khi bạn xem dashboard cá nhân:

### 4.1. TV hợp lệ (Verified Consultations)

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Số leads bạn tư vấn hôm nay mà có thay đổi trạng thái thực sự trên hệ thống |
| **Cách tính** | Đếm leads DISTINCT được tư vấn hôm nay + có cập nhật pipeline + loại tư vấn hệ thống |

Một tư vấn "hợp lệ" là khi bạn tư vấn VÀ cập nhật trạng thái lead trên hệ thống.

### 4.2. Tỷ lệ chất lượng

| | Chi tiết |
|---|---------|
| **Cách tính** | `TV hợp lệ / Tổng tư vấn hôm nay × 100` |

Nếu bạn tư vấn 10 leads nhưng chỉ 6 leads có cập nhật trạng thái → tỷ lệ = 60%

### 4.3. Cam kết follow-up

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Trong số TV hợp lệ cho leads chưa kết thúc, bao nhiêu % có đặt lịch hẹn tiếp? |

Hệ thống đo xem bạn có chủ động đặt lịch follow-up hay không.

### 4.4. Tiến triển D+7

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Leads bạn tư vấn 7 ngày trước — bao nhiêu % đã tiến lên giai đoạn tiếp? |

Đo hiệu quả dài hạn: tư vấn hôm nay có tạo ra tiến triển thực sự không?

### 4.5. Tụt hạng D+3

| | Chi tiết |
|---|---------|
| **Ý nghĩa** | Leads bạn tư vấn 3 ngày trước — bao nhiêu % bị tụt về giai đoạn trước? |
| **Càng THẤP càng tốt** | Có — 0% là lý tưởng |

---

## 5. Biểu đồ phễu tuyển sinh

Biểu đồ phễu cho thấy leads đang phân bố ở đâu trong quy trình:

```
 ┌─────────────────────────────────────────────┐
 │           Chưa tư vấn: 20 leads             │  ← Leads mới, cần liên hệ
 ├───────────────────────────────────────┤
 │         Đang tư vấn: 45 leads        │  ← Đang xử lý
 ├────────────────────────┤
 │   Đã nộp hồ sơ: 1     │
 ├──────────┤
 │  Kết quả │
 ├──────┤
 │ Học phí│
 └──────┘
```

### Đọc phễu thế nào?

- **Thanh rộng nhất** = giai đoạn có nhiều leads nhất → đây là nơi bạn cần tập trung
- **Click vào bất kỳ thanh nào** → xem danh sách leads chi tiết tại giai đoạn đó
- **% bên cạnh** = tỷ lệ leads ở giai đoạn này so với tổng
- **Bottleneck** (biểu tượng cảnh báo) = giai đoạn có tỷ lệ chuyển đổi thấp nhất

---

## 6. Mục tiêu (Target)

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

### Khi nào hiện target trên dashboard?

- Một số KPI chỉ hiện target khi bạn xem đúng kỳ (ví dụ: Win Rate chỉ so sánh khi xem theo tháng)
- Một số KPI chỉ hiện xu hướng (mũi tên lên/xuống) mà không so target

---

## 7. Mẹo để đạt target

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
- Đừng dồn thời gian vào leads "Từ chối tư vấn" quá lâu → chuyển sang leads tiềm năng hơn
- Giải quyết lo ngại của học viên: học phí (PRICE_HIGH), thời điểm (TIMING_BAD)
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

- **Luôn cập nhật trạng thái** sau mỗi cuộc tư vấn → tăng TV hợp lệ
- **Đặt lịch hẹn tiếp** cho leads chưa kết thúc → tăng cam kết follow-up
- **Xem D+7 và D+3** mỗi sáng → biết leads nào cần chú ý đặc biệt

---

## 8. Câu hỏi thường gặp

### "Tại sao tư vấn của tôi không được đếm?"

Kiểm tra:
- Bạn có tạo consultation trên hệ thống không? (không chỉ gọi điện mà phải ghi nhận)
- Consultation có phải do hệ thống tự tạo (method=system) không? → không tính
- Consultation có bị xóa không?

### "Tại sao SLA của tôi thấp?"

SLA đếm cả leads bạn **chưa liên hệ** mà đã quá 2 giờ. Ví dụ: 9 leads chưa gọi + quá hạn → tất cả đều bị tính vi phạm SLA.

**Giải pháp:** Liên hệ leads mới ngay khi được giao, ít nhất gọi 1 cuộc dù ngắn.

### "Win Rate 0% nhưng tôi đang làm tốt mà?"

Win Rate chỉ tính leads **đã kết thúc** (nhập học hoặc mất). Nếu chưa có lead nào kết thúc trong kỳ → Win Rate = 0% (không có đủ dữ liệu, không phải bạn làm kém).

### "Số trên phễu không bằng Leads đang xử lý?"

Bình thường. Phễu chỉ đếm leads có trạng thái tư vấn thuộc phễu (counts_for_funnel). Một số trạng thái hoạt động (Không nghe máy, Nhắn tin không phản hồi, Hủy hẹn) không nằm trong phễu nhưng vẫn tính là "đang xử lý".

### "Thời gian phản hồi tính từ lúc nào?"

Từ lúc **lead được giao cho bạn** (assigned_at) đến lần tư vấn **đầu tiên** bạn thực hiện. Nếu lead được giao lúc 8:00 sáng và bạn gọi lúc 2:00 chiều → 6 giờ.

### "Mũi tên xu hướng so sánh với gì?"

So sánh với **cùng khoảng thời gian trước đó**. Ví dụ: nếu bạn đang xem 7 ngày gần nhất (18-24/3), hệ thống so với 7 ngày trước đó (11-17/3).

### "Tôi có thể xem KPI của người khác không?"

- **Tư vấn viên**: chỉ xem được dashboard cá nhân
- **Quản lý**: xem được dashboard đơn vị (tất cả tư vấn viên trong đơn vị)
- **Admin**: xem được toàn bộ tổ chức + drill-down vào từng tư vấn viên

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
