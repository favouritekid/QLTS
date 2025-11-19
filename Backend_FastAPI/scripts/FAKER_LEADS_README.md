# 🎯 Script Faker: Tạo Lead Mẫu

Script này giúp tạo dữ liệu Lead mẫu cho hệ thống QLTS với dữ liệu ngẫu nhiên nhưng thực tế.

## 📋 Tính Năng

- ✅ Tạo N leads với dữ liệu Tiếng Việt
- ✅ Random phân bố qua units, program offerings, sources
- ✅ Tự động calculate lead_score dựa trên config
- ✅ Hỗ trợ tạo kèm consultations ngẫu nhiên
- ✅ Batch processing để tránh timeout
- ✅ Error handling và summary report

## 🔧 Cài Đặt

### 1. Install Dependencies

```bash
cd Backend_FastAPI
pip install Faker
```

Hoặc cài tất cả dependencies:

```bash
pip install -r requirements.txt
```

### 2. Verify Database Connection

Đảm bảo file `.env` có cấu hình database chính xác:

```env
DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/qlts
```

## 📖 Cách Sử Dụng

### Syntax

```bash
python scripts/faker_leads.py [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--count` | int | 50 | Số lượng leads cần tạo |
| `--unit-id` | int | None | Chỉ tạo leads cho unit_id cụ thể (optional) |
| `--with-consultations` | flag | False | Tạo kèm consultations ngẫu nhiên |
| `--batch-size` | int | 50 | Số leads tạo trong mỗi batch |

### Examples

#### 1. Tạo 50 Leads (Default)

```bash
python scripts/faker_leads.py
```

#### 2. Tạo 100 Leads

```bash
python scripts/faker_leads.py --count 100
```

#### 3. Tạo 200 Leads với Consultations

```bash
python scripts/faker_leads.py --count 200 --with-consultations
```

#### 4. Tạo 50 Leads cho Unit Cụ Thể (Unit ID = 1)

```bash
python scripts/faker_leads.py --count 50 --unit-id 1
```

#### 5. Tạo 500 Leads với Batch Size Nhỏ Hơn

```bash
python scripts/faker_leads.py --count 500 --batch-size 25
```

#### 6. Full Options

```bash
python scripts/faker_leads.py \
  --count 300 \
  --unit-id 2 \
  --with-consultations \
  --batch-size 50
```

## 📊 Dữ Liệu Được Tạo

### Lead Fields

| Field | Type | Generated Data |
|-------|------|----------------|
| `full_name` | string | Tên Tiếng Việt từ danh sách có sẵn |
| `email` | EmailStr | {username}@{domain} (gmail, yahoo, outlook, etc.) |
| `phone` | string | Số điện thoại Vietnam format |
| `source` | string | website, referral, social_media, walk_in, email, phone, event, other |
| `education_level` | string | high_school, bachelor, master, phd |
| `gpa` | float | 2.0 - 4.0 (70% có giá trị, 30% null) |
| `location` | string | Tỉnh/Thành phố Việt Nam (Hà Nội, HCM, Đà Nẵng, ...) |
| `unit_id` | int | Random từ danh sách units active |
| `offering_id` | int | Random từ program offerings (80% có giá trị) |
| `officer_rating` | int | 1-5 (30% có giá trị) |
| `officer_summary` | string | Summary ngắn (nếu có rating) |
| `lead_score` | int | **Auto-calculated** dựa trên education, GPA, source, location |

### Consultations (nếu `--with-consultations`)

Mỗi lead sẽ có **1-3 consultations** ngẫu nhiên:

| Field | Generated Data |
|-------|----------------|
| `method` | phone, email, in_person, video_call, chat |
| `notes` | Template notes Tiếng Việt (8 templates) |
| `outcome` | positive, neutral, negative, null |
| `duration_minutes` | 10-90 phút (50% có giá trị) |
| `status_id` | Random từ consultation_statuses table |
| `officer_id` | Random active officer |

## 🎲 Vietnamese Data Quality

Script sử dụng **Faker locale [`vi_VN`, `en_US`]** và danh sách tên Tiếng Việt có sẵn:

```python
VIETNAMESE_NAMES = [
    "Nguyễn Văn An", "Trần Thị Bình", "Lê Hoàng Cường", ...
]

LOCATIONS = [
    "Hà Nội", "Hồ Chí Minh", "Đà Nẵng", "Hải Phòng", ...
]

CONSULTATION_NOTES = [
    "Học viên quan tâm chương trình đào tạo, cần tư vấn thêm về học phí",
    "Đã giải đáp thắc mắc về điều kiện đầu vào và thời gian học",
    ...
]
```

## 📈 Output Example

```
======================================================================
🎯 QLTS LEAD FAKER SCRIPT
======================================================================
📌 Configuration:
   - Total leads to create: 100
   - Target unit: All units (random)
   - With consultations: True
   - Batch size: 50
======================================================================
📊 Loading reference data from database...
   ✅ Units: 5
   ✅ Offerings: 12
   ✅ Consultation Statuses: 8
   ✅ Officers: 10

🔧 Creating batch of 50 leads...
   ✅ Created 10/50 leads...
   ✅ Created 20/50 leads...
   ✅ Created 30/50 leads...
   ✅ Created 40/50 leads...
   ✅ Created 50/50 leads...
   💾 Batch committed to database

🔧 Creating batch of 50 leads...
   ✅ Created 10/50 leads...
   ✅ Created 20/50 leads...
   ✅ Created 30/50 leads...
   ✅ Created 40/50 leads...
   ✅ Created 50/50 leads...
   💾 Batch committed to database

======================================================================
✅ FAKER SCRIPT COMPLETED
======================================================================
📊 Summary:
   - Total leads created: 100
   - Total errors: 0
   - Success rate: 100.0%
======================================================================
```

## ⚠️ Lưu Ý

### 1. Database Prerequisites

Script yêu cầu các bảng sau phải có dữ liệu:

- ✅ `organization_unit` (ít nhất 1 unit active)
- ✅ `consultation_status` (ít nhất 1 status)
- ⚠️ `program_offering` (optional - nếu không có, leads sẽ có `offering_id = null`)
- ⚠️ `user` với `role = 'officer'` (optional - nếu không có, không tạo consultations)

### 2. Email Uniqueness

Script **KHÔNG kiểm tra** email duplicate trong DB. Nếu tạo nhiều lần có thể gặp lỗi:

```
❌ Row 12: duplicate key value violates unique constraint "uq_lead_email_unit"
```

**Giải pháp:** Script sẽ skip rows lỗi và tiếp tục tạo các leads còn lại.

### 3. Performance

- **Batch size lớn** (100+): Nhanh hơn nhưng có thể timeout với consultations
- **Batch size nhỏ** (25-50): Chậm hơn nhưng ổn định hơn
- **With consultations**: Tăng thời gian tạo lên ~3x (vì cần assign officers + create consultations)

**Khuyến nghị:**
- Không dùng `--with-consultations`: Batch size 100
- Dùng `--with-consultations`: Batch size 25-50

### 4. Celery Auto-Assignment

Sau khi tạo lead, hệ thống sẽ **dispatch Celery task** để auto-assign:

```python
process_automatic_lead_assignment_task.delay(lead.id)
```

Nếu Celery worker KHÔNG chạy:
- ✅ Lead vẫn được tạo thành công
- ⚠️ Lead sẽ có `assigned_officer_id = null` (status = "unassigned")
- 💡 Bạn có thể assign thủ công sau qua UI/API

## 🐛 Troubleshooting

### Error: "No active organization units found"

```bash
❌ ERROR: No active organization units found! Please create units first.
```

**Giải pháp:** Tạo ít nhất 1 Organization Unit trong database:

```sql
INSERT INTO organization_unit (name, type, is_active)
VALUES ('Phòng Tuyển Sinh', 'department', true);
```

### Error: "Connection refused"

```bash
sqlalchemy.exc.OperationalError: connection to server at "localhost", port 5432 failed
```

**Giải pháp:**
1. Kiểm tra PostgreSQL đang chạy: `systemctl status postgresql`
2. Kiểm tra `.env` có `DATABASE_URL` chính xác
3. Test connection: `psql -U user -d qlts`

### Error: "Faker module not found"

```bash
ModuleNotFoundError: No module named 'faker'
```

**Giải pháp:**

```bash
pip install Faker
```

### High Error Rate

```
📊 Summary:
   - Total leads created: 50
   - Total errors: 50
   - Success rate: 50.0%
```

**Nguyên nhân thường gặp:**
1. Email duplicate (chạy script nhiều lần)
2. Foreign key constraint fails (unit_id, offering_id không tồn tại)
3. Database connection timeout

**Giải pháp:**
- Kiểm tra error messages chi tiết trong output
- Giảm `--batch-size`
- Check database constraints

## 📚 Liên Quan

- **Lead Service:** `app/services/lead_service.py`
- **Lead Model:** `app/models/lead.py`
- **Lead Schemas:** `app/schemas/lead.py`
- **Distribution Service:** `app/services/distribution_service.py`

## 🤝 Contributing

Nếu muốn thêm features:

1. **Thêm tên Tiếng Việt mới:** Edit `VIETNAMESE_NAMES` list
2. **Thêm consultation notes templates:** Edit `CONSULTATION_NOTES` list
3. **Thêm locations:** Edit `LOCATIONS` list
4. **Custom logic:** Edit `generate_random_lead()` function

---

**Version:** 1.0
**Author:** QLTS Development Team
**Last Updated:** 2025-11-18
