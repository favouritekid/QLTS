// src/app/(dashboard)/settings/layout.tsx
import React from "react";
import { SettingsNav } from "./_components/SettingsNav"; // Component điều hướng ta sẽ tạo ở bước 3

/**
 * Đây là Layout chung cho TẤT CẢ các trang con trong /settings/*
 * Nó cung cấp tiêu đề chung và thanh điều hướng Tab.
 * {children} sẽ là nội dung của trang con (ví dụ: page.tsx hoặc sessions/page.tsx)
 */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="space-y-6">
      {/* 1. Tiêu đề chung của trang Cài đặt */}
      <header>
        <h1 className="text-3xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">
          Manage your account settings, password, and active sessions.
        </p>
      </header>

      {/* 2. Thanh điều hướng dạng Tab */}
      <SettingsNav />

      {/* 3. Render nội dung của tab đang được chọn (children) */}
      <div className="pt-4">{children}</div>
    </div>
  );
}
