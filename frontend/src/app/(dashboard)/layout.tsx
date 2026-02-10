// src/app/(dashboard)/layout.tsx
"use client";

import { DashboardLayout } from "@/components/layouts/DashboardLayout";
import dynamic from "next/dynamic";
import React from "react";

// ✅ PERF: Lazy-load SocketHandler - renders null, chỉ cần ở client
const SocketHandler = dynamic(
  () => import("@/components/layouts/SocketHandler").then(m => ({ default: m.SocketHandler })),
  { ssr: false }
);

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <DashboardLayout>
      {children}
      <SocketHandler />
    </DashboardLayout>
  );
}
