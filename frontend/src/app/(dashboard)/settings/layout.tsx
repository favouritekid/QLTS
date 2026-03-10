// src/app/(dashboard)/settings/layout.tsx
import React from "react";
import { PageContainer } from "@/components/layouts/PageContainer";
import { PageHeader } from "@/components/layouts/PageHeader";
import { SettingsNav } from "./_components/SettingsNav"; // Component điều hướng ta sẽ tạo ở bước 3

/**
 * Đây là Layout chung cho TẤT CẢ các trang con trong /settings/*
 * Nó cung cấp tiêu đề chung và thanh điều hướng Tab.
 * {children} sẽ là nội dung của trang con (ví dụ: page.tsx hoặc sessions/page.tsx)
 */
export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  return (
    <PageContainer maxWidth="md">
      {/* 1. Tiêu đề chung của trang Cài đặt */}
      <PageHeader
        title="Cài đặt"
        description="Quản lý cài đặt tài khoản, mật khẩu và phiên đăng nhập."
      />

      {/* 2. Thanh điều hướng dạng Tab */}
      <SettingsNav />

      {/* 3. Render nội dung của tab đang được chọn (children) */}
      <div className="pt-4">{children}</div>
    </PageContainer>
  );
}
