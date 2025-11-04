# 📦 Codebase Export Guide

Hướng dẫn sử dụng script `export_codebase_to_markdown.py` để export toàn bộ mã nguồn dự án sang định dạng Markdown.

---

## 🎯 Tính năng

### ✅ Các chức năng chính:

1. **Export riêng biệt:**
   - Frontend only → `FRONTEND_SOURCE.md`
   - Backend only → `BACKEND_SOURCE.md`

2. **Export kết hợp:**
   - Frontend + Backend → `FULL_CODEBASE_EXPORT.md`

3. **Export tất cả:**
   - Tạo cả 3 files trên cùng lúc

### 📊 Thông tin được export:

- ✅ Cấu trúc thư mục (tree structure)
- ✅ Toàn bộ source code với syntax highlighting
- ✅ Số dòng code cho mỗi file
- ✅ Kích thước file
- ✅ Thống kê tổng quan (số files, tổng số dòng, tổng kích thước)
- ✅ Timestamp và metadata

### 🚫 Files được loại trừ:

**Thư mục:**
- `node_modules/`, `venv/`, `.venv/`
- `dist/`, `build/`, `.next/`, `__pycache__/`
- `.git/`, `.github/`, `.vscode/`, `.idea/`
- `coverage/`, `logs/`, `tmp/`

**Files:**
- `.env`, `.env.local`, `.env.production`
- `package-lock.json`, `yarn.lock`, `poetry.lock`
- `*.md` (documentation files)
- `.gitignore`, `.dockerignore`

---

## 🚀 Cách sử dụng

### **1. Export tất cả (Khuyến nghị)**

```bash
python export_codebase_to_markdown.py
```

**Kết quả:**
- `exports/FRONTEND_SOURCE.md` - Frontend source code
- `exports/BACKEND_SOURCE.md` - Backend source code
- `exports/FULL_CODEBASE_EXPORT.md` - Combined source code

---

### **2. Export chỉ Frontend**

```bash
python export_codebase_to_markdown.py --mode frontend
```

**Kết quả:**
- `exports/FRONTEND_SOURCE.md`

**Bao gồm:**
- `frontend/src/` - Tất cả TypeScript/JavaScript files
- Components (`.tsx`, `.ts`)
- Hooks, stores, utilities
- API clients, types
- Styles (`.css`, `.scss`)

---

### **3. Export chỉ Backend**

```bash
python export_codebase_to_markdown.py --mode backend
```

**Kết quả:**
- `exports/BACKEND_SOURCE.md`

**Bao gồm:**
- `Backend_FastAPI/app/` - Tất cả Python files
- Routers, models, schemas
- Services, core modules
- Database, security utilities
- Configuration files

---

### **4. Export file kết hợp**

```bash
python export_codebase_to_markdown.py --mode combined
```

**Kết quả:**
- `exports/FULL_CODEBASE_EXPORT.md`

**Bao gồm:**
- Frontend + Backend trong một file duy nhất
- Table of Contents
- Statistics section

---

### **5. Chỉ định thư mục dự án**

```bash
python export_codebase_to_markdown.py --project-root /path/to/project
```

Mặc định: Thư mục hiện tại (`d:\QLTS`)

---

## 📁 Cấu trúc Output

### **FRONTEND_SOURCE.md**

```markdown
# Frontend Source Code

**Generated:** 2025-11-04 10:30:00
**Project:** QLTS (Quản Lý Tài Sản)

## 📁 Directory Structure

```
frontend/src/
├── app/
│   ├── layout.tsx
│   └── page.tsx
├── components/
│   ├── layouts/
│   │   └── DashboardLayout.tsx
│   └── ui/
├── hooks/
│   └── useAuth.ts
├── lib/
│   ├── api/
│   │   ├── auth.ts
│   │   └── client.ts
│   └── stores/
│       └── auth.store.ts
└── types/
    └── api.types.ts
```

## 📝 Source Files

## 📄 `app/layout.tsx`

**Lines:** 45 | **Size:** 1234 bytes

```typescript
import type { Metadata } from 'next'
...
```

## 📄 `components/layouts/DashboardLayout.tsx`

**Lines:** 120 | **Size:** 3456 bytes

```typescript
'use client'
import { useEffect, useRef } from 'react'
...
```
```

---

### **BACKEND_SOURCE.md**

```markdown
# Backend Source Code

**Generated:** 2025-11-04 10:30:00
**Project:** QLTS (Quản Lý Tài Sản)

## 📁 Directory Structure

```
Backend_FastAPI/app/
├── routers/
│   ├── auth.py
│   ├── sessions.py
│   └── users.py
├── models/
│   ├── user.py
│   └── user_session.py
├── schemas/
│   ├── user.py
│   └── user_session.py
├── services/
│   ├── session_service.py
│   └── user_service.py
├── core/
│   ├── deps.py
│   └── config.py
├── database.py
├── security.py
└── main.py
```

## 📝 Source Files

## 📄 `routers/auth.py`

**Lines:** 760 | **Size:** 25678 bytes

```python
from fastapi import APIRouter, Depends, HTTPException
...
```
```

---

### **FULL_CODEBASE_EXPORT.md**

```markdown
# Complete Project Source Code

**Generated:** 2025-11-04 10:30:00
**Project:** QLTS (Quản Lý Tài Sản)

## 📑 Table of Contents

1. [Frontend Source Code](#frontend-source-code)
2. [Backend Source Code](#backend-source-code)
3. [Statistics](#statistics)

---

## 📊 Statistics

### Frontend
- **Files:** 45
- **Lines of Code:** 12,345
- **Total Size:** 456.78 KB

### Backend
- **Files:** 38
- **Lines of Code:** 15,678
- **Total Size:** 567.89 KB

### Total
- **Files:** 83
- **Lines of Code:** 28,023
- **Total Size:** 1.00 MB

---

# Frontend Source Code

...

---

# Backend Source Code

...
```

---

## 📊 Ước tính kích thước

### **Dự án QLTS hiện tại:**

**Frontend:**
- Ước tính: ~50-60 files
- Ước tính: ~15,000-20,000 dòng code
- Output size: ~2-3 MB

**Backend:**
- Ước tính: ~40-50 files
- Ước tính: ~20,000-25,000 dòng code
- Output size: ~2-3 MB

**Combined:**
- Output size: ~5-7 MB

**Lưu ý:** Files Markdown có thể lớn, nhưng vẫn có thể mở được bằng text editor hoặc Markdown viewer.

---

## 🔧 Tùy chỉnh

### **Thêm/bớt file extensions:**

Chỉnh sửa trong `export_codebase_to_markdown.py`:

```python
FRONTEND_EXTENSIONS = {
    '.ts', '.tsx', '.js', '.jsx',
    '.css', '.scss', '.sass', '.less',
    '.json', '.html', '.svg'
    # Thêm extensions khác nếu cần
}

BACKEND_EXTENSIONS = {
    '.py', '.pyi', '.txt', '.yml', '.yaml',
    '.toml', '.ini', '.cfg', '.conf'
    # Thêm extensions khác nếu cần
}
```

### **Thêm/bớt thư mục loại trừ:**

```python
EXCLUDE_DIRS = {
    'node_modules', 'venv', '.venv',
    'dist', 'build', '.next', '__pycache__',
    # Thêm thư mục khác nếu cần
}
```

### **Bao gồm Markdown files:**

Xóa dòng này trong `EXCLUDE_PATTERNS`:

```python
EXCLUDE_PATTERNS = {
    # '*.md', '*.MD'  # Comment out để bao gồm .md files
}
```

---

## 🐛 Troubleshooting

### **Lỗi: "Directory not found"**

**Nguyên nhân:** Script không tìm thấy thư mục `frontend/src/` hoặc `Backend_FastAPI/app/`

**Giải pháp:**
```bash
# Chạy từ thư mục gốc dự án
cd d:\QLTS
python export_codebase_to_markdown.py

# Hoặc chỉ định project root
python export_codebase_to_markdown.py --project-root d:\QLTS
```

---

### **Lỗi: "UnicodeDecodeError"**

**Nguyên nhân:** File có encoding không phải UTF-8

**Giải pháp:** Script tự động fallback sang `latin-1` encoding. Nếu vẫn lỗi, file sẽ hiển thị error message.

---

### **File output quá lớn**

**Giải pháp:**
1. Export riêng frontend và backend thay vì combined
2. Loại trừ thêm file types không cần thiết
3. Sử dụng text editor hỗ trợ large files (VS Code, Sublime Text)

---

## 📝 Use Cases

### **1. Documentation**
- Tạo documentation đầy đủ cho dự án
- Chia sẻ với team members
- Lưu trữ snapshot của codebase

### **2. AI Analysis**
- Upload vào ChatGPT/Claude để phân tích
- Code review tự động
- Tìm bugs, security issues
- Suggest improvements

### **3. Code Migration**
- Backup trước khi refactor lớn
- So sánh versions
- Migration planning

### **4. Learning & Training**
- Study material cho developers mới
- Code examples
- Architecture overview

---

## ✅ Checklist trước khi export

- [ ] Đã commit/push code mới nhất
- [ ] Đã xóa các files test/debug không cần thiết
- [ ] Đã kiểm tra không có sensitive data (API keys, passwords)
- [ ] Đã chọn mode export phù hợp
- [ ] Có đủ disk space cho output files (~10-20 MB)

---

## 🎉 Hoàn thành

Sau khi chạy script, bạn sẽ có:

✅ Files Markdown được format đẹp với syntax highlighting  
✅ Cấu trúc thư mục rõ ràng  
✅ Thống kê chi tiết  
✅ Dễ dàng search và navigate  
✅ Sẵn sàng để share hoặc analyze  

**Happy exporting! 🚀**

