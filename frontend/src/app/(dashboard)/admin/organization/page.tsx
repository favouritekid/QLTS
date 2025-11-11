// src/app/(dashboard)/admin/organization/page.tsx

// 1. Thêm "use client" ở đầu file
"use client";

// 2. Import 'dynamic' và 'Skeleton'
import dynamic from "next/dynamic";
import { Skeleton } from "@/components/ui/skeleton";

// 3. Dynamic import component 'OrganizationClientPage' và tắt SSR
const OrganizationClientPage = dynamic(
  () =>
    import("@/components/admin/organization/OrganizationClientPage").then(
      (mod) => mod.OrganizationClientPage
    ),
  {
    ssr: false, // <-- Tắt Server-Side Rendering cho component này
    loading: () => (
      // Hiển thị skeleton loading
      <div className="flex h-[calc(100vh-4rem)] overflow-hidden">
        <Skeleton className="w-80 border-r" />
        <div className="flex-1 p-6">
          <Skeleton className="h-16 w-1/3" />
        </div>
      </div>
    ),
  }
);

/**
 * Organization Management Page
 * (Mô tả giữ nguyên)
 */
export default function OrganizationPage() {
  return (
    <div className="h-[calc(100vh-4rem)]">
      {/* 4. Render component đã được dynamic import */}
      <OrganizationClientPage />
    </div>
  );
}
