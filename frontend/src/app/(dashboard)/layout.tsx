// src/app/(dashboard)/layout.tsx
import { DashboardLayout } from "@/components/layouts/DashboardLayout";
// ✅ SỬA LỖI: Thêm dòng import còn thiếu
import { SocketHandler } from "@/components/layouts/SocketHandler";
import React from "react";

export default function Layout({ children }: { children: React.ReactNode }) {
  // Layout này sẽ bọc tất cả các trang con
  // ví dụ: /dashboard, /settings, /profile
  return (
    <DashboardLayout>
      {children}
      {/* Component này sẽ được import chính xác */}
      <SocketHandler />
    </DashboardLayout>
  );
}
