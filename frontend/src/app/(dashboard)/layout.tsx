// src/app/(dashboard)/layout.tsx
import { DashboardLayout } from "@/components/layouts/DashboardLayout";
import React from "react";

export default function Layout({ children }: { children: React.ReactNode }) {
  // Layout này sẽ bọc tất cả các trang con
  // ví dụ: /dashboard, /settings, /profile
  return <DashboardLayout>{children}</DashboardLayout>;
}
