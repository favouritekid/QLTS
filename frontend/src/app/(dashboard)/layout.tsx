// src/app/(dashboard)/layout.tsx
import { DashboardLayout } from "@/components/layouts/DashboardLayout";
import dynamic from "next/dynamic";
import React from "react";

// ✅ PERF: Lazy-load SocketHandler - renders null, chỉ cần ở client
const SocketHandler = dynamic(
  () => import("@/components/layouts/SocketHandler").then(m => ({ default: m.SocketHandler })),
  { ssr: false }
);

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
