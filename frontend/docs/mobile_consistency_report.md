# Báo cáo Rà soát Đồng nhất Layout & Padding (Mobile Focus)

**Thời gian rà soát:** 2026-01-29
**Phạm vi:** Dashboard, Leads, Admissions, Notifications, Profile, Settings, Admin Pages.

## 1. Cơ chế Layout Toàn cục (Global Layout Mechanism)

Hệ thống sử dụng cơ chế 2 lớp để quản lý padding và margin:

1.  **Lớp vỏ `Main.tsx` (`src/components/layouts/dashboard/Main.tsx`)**:
    *   **Padding Mặc định**: Mã nguồn quy định `p-3 md:p-4 lg:p-6`.
    *   **Mobile Spacing**: Được quản lý bởi `DashboardLayout`, tự động thêm `pb-20` (padding-bottom) để tránh bị thanh điều hướng dưới (Bottom Nav) che khuất.
    *   **Đồng nhất**: ✅ Tất cả các trang đều nằm trong wrapper này.

2.  **Lớp con `PageContainer` (`src/components/layouts/PageContainer.tsx`)**:
    *   **Chức năng**: Giới hạn chiều rộng nội dung (`max-w-*`) và căn giữa (`mx-auto`).
    *   **Padding bổ sung**: Sử dụng biến CSS `py-[var(--page-padding-y)]`.
    *   **Overflow**: Có `overflow-x-clip` để ngăn vỡ layout ngang.

## 2. Kết quả Rà soát Từng Trang

| Trang / Module | Component Chính | Sử dụng PageContainer? | Trạng thái Layout | Ghi chú / Vấn đề |
| :--- | :--- | :--- | :--- | :--- |
| **Dashboard** | `DashboardClient` | ✅ Có | **Chuẩn** | Tuân thủ padding toàn cục. |
| **Leads** | `PipelineClient` | ✅ Có | **Chuẩn** | Grid và Kanban board nằm gọn trong container. |
| **Admissions** | `AdmissionsPage` | ✅ Có | **Chuẩn** | Sử lụng `maxWidth="xl"`, hiển thị tốt. |
| **Notifications** | `NotificationsClient` | ✅ Có | **Chuẩn** | Sử dụng `maxWidth="md"`, padding cân đối. |
| **Settings** | `Layout` wrapper | ✅ Có | **Chuẩn** | Layout cha bọc `PageContainer`, các trang con không cần bọc lại. |
| **Admin** | `AdminUsersClient` | ✅ Có | **Chuẩn** | Table full-width nhưng vẫn có padding lề đúng. |
| **Profile** | `ProfileClient` | ⚠️ **Không** | **Chưa đồng nhất** | Sử dụng padding cứng: `px-4 md:px-6`. **Hệ quả**: Padding bị nhân đôi (Main padding + Profile padding) => Lề rộng hơn các trang khác khoảng 16px. |

## 3. Phân tích Chi tiết Vấn đề (Discrepancies)

### ⚠️ Profile Page Inconsistency
-   **Hiện tại**: `src/app/(dashboard)/profile/_components/ProfileClient.tsx`
    ```tsx
    <div className="px-4 md:px-6 py-4 md:py-6 space-y-4 md:space-y-6">
    ```
-   **Vấn đề**: Do `Main` đã có `p-3` (mobile), việc thêm `px-4` khiến tổng padding là ~28px, lớn hơn chuẩn 12px. Điều này khiến nội dung trang Profile trông "thu hẹp" hơn so với các trang khác.
-   **Đề xuất Fix**: Thay thế `div` wrapper bằng `<PageContainer>` hoặc xóa class padding thủ công (chỉ giữ lại `space-y`).

### ✅ Sidebar overlay
-   **Đã Fix**: Sidebar Overlay mặc định `Collapsed` nên không còn che khuất nội dung.

## 4. Kết luận & Khuyến nghị

1.  **Độ đồng nhất (Consistency Score)**: **90%**. Hầu hết các trang đều tuân thủ `PageContainer` pattern.
2.  **Hành động ngay**:
    -   (Optional) Refactor `ProfileClient.tsx` để sử dụng `PageContainer` thay vì padding thủ công để đạt 100% đồng nhất.
3.  **Xác nhận hiển thị**: Các ảnh chụp màn hình mới nhất (`mobile_checks_final`) đã xác nhận nội dung hiển thị rõ ràng, không bị che khuất, margin lề an toàn.
