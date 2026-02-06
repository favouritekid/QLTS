# Mobile Standardization Guide (Best Practices v2.0)

> **Mục tiêu**: Đảm bảo trải nghiệm nhất quán, không lỗi trên mọi thiết bị di động (375px+).
> **Nguyên tắc cốt lõi**: Mobile-First, Configuration-Driven, Automated Testing.

---

## 1. Nguyên tắc Kiến trúc (Architecture Rules)

### 1.1 Layout Wrapper (BẮT BUỘC)
Mọi Layout đều phải tuân thủ mô hình "2 lớp" để đảm bảo margin/padding đồng nhất:

1.  **Lớp 1 (Global)**: `Main.tsx` chịu trách nhiệm padding tổng thể.
    *   ❌ Cấm hardcode `p-4`, `m-4` trong từng page con.
    *   ✅ Sử dụng class chuẩn biên dịch từ `Main`: `p-3 md:p-4 lg:p-6`.

2.  **Lớp 2 (Content)**: `PageContainer.tsx` chịu trách nhiệm giới hạn nội dung.
    *   ✅ Luôn bọc nội dung trong `<PageContainer>`.
    *   ✅ Sử dụng props `maxWidth` (sm, md, lg, xl) thay vì width cứng.

```tsx
// ✅ CHUẨN (Standard)
export function UserProfile() {
  return (
    <PageContainer maxWidth="md">
        <Card>...</Card>
    </PageContainer>
  )
}

// ❌ SAI (Violation) - Gây lệch lề
export function UserProfile() {
  return (
    <div className="px-4 py-6"> {/* KHÔNG tự thêm padding */}
        <Card>...</Card>
    </div>
  )
}
```

### 1.2 State Management & Defaults
Trạng thái UI mặc định phải CỰC KỲ an toàn cho Mobile.

*   **Sidebar**: Mặc định `isSidebarCollapsed: true`.
    *   Lý do: Tránh flash content (FOUC) hoặc overlay che khuất nội dung khi load trang trên mobile.
*   **Filters**: Mặc định `hidden` hoặc `collapsed` (Accordion).
*   **Tables**: Mặc định ẩn bớt cột phụ (`hidden md:table-cell`).

---

## 2. Quy chuẩn Component (Component Patterns)

### 2.1 Inputs & Touch Targets
*   **Chiều cao**: Tối thiểu `44px` (Touch target chuẩn). Class: `h-11` (Tailwind).
*   **Font size**: Tối thiểu `16px` để tránh iOS tự động zoom.

### 2.2 Modal & Overlays
*   **Chiều rộng**: `mx-4` (có lề) hoặc `w-full` (full width sheet).
*   **Chiều cao**: `max-h-[85vh]` + `overflow-y-auto`. Không bao giờ để modal tràn màn hình không cuộn được.
*   **Vị trí**: Ưu tiên `Bottom Sheet` (Drawer) trên mobile thay vì Center Modal.

### 2.3 Data Display
*   Desktop: **Table**.
*   Mobile: **Card View**.
*   Sử dụng component `ResponsiveDataDisplay` để tự động chuyển đổi.

---

## 3. Chiến lược Kiểm thử Tự động (Testing Strategy)

Không tin tưởng vào check thủ công. Sử dụng **Playwright** với cấu hình Mobile.

### 3.1 Script chuẩn (`mobile_checks_final.spec.ts`)
Mọi thay đổi UI lớn đều phải vượt qua bài test này:

1.  **Viewport**: iPhone 11/12 (`375x812`).
2.  **State Injection**: Ép buộc trạng thái clean trước khi test.
    ```typescript
    await page.addInitScript(() => {
        // Luôn đóng Sidebar để tránh che screenshot
        window.localStorage.setItem('ui-storage', JSON.stringify({ 
            state: { isSidebarCollapsed: true }, version: 0 
        }));
    });
    ```
3.  **Screenshot Comparison**: Chụp ảnh toàn trang (`fullPage: true`) để review.

### 3.2 Checklist Review Code (PR Checklist)
- [ ] Page có bọc `PageContainer` không?
- [ ] Input có dùng `h-11` (mobile) không?
- [ ] Table có chế độ Card View cho mobile không?
- [ ] Đã chạy `npm run test:e2e:mobile` chưa?

---

## 4. Workflows & Scripts

### Run Mobile Check
```bash
npx playwright test src/test/e2e/mobile_checks_final.spec.ts --project=chromium
```

### Fix Layout Inconsistency
Tìm các file vi phạm `PageContainer`:
```bash
grep -r "className=\"p-" src/app/\(dashboard\) | grep -v "PageContainer"
```

---

> **Note**: Tài liệu này là nguồn sự thật (Source of Truth). Mọi PR vi phạm các quy tắc trên sẽ bị từ chối (Request Changes).
