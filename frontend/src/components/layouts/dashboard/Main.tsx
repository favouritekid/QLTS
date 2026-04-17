// src/components/layouts/dashboard/Main.tsx
"use client";

import { cn } from "@/lib/utils";
import React, { Suspense } from "react";
import { Breadcrumbs } from "@/components/common/Breadcrumbs";

export function Main({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <main
      id="main-content"
      className={cn(
        // Padding và spacing - Responsive padding for mobile
        "flex-1 p-3 md:p-4 lg:p-6",
        // Overflow control - allow vertical scroll, contain horizontal within children
        "overflow-y-auto overflow-x-hidden",
        // Min height để đảm bảo chiếm toàn bộ viewport
        "min-h-[calc(100vh-3.5rem)]",
        className
      )}
    >
      {/* Container với max-width và spacing - uses --content-max-width and --content-gap */}
      {/* w-full + min-w-0 + max-w-full ensures container stays within bounds */}
      <div className="mx-auto w-full min-w-0 max-w-full lg:max-w-[var(--content-max-width)] space-y-[var(--content-gap)]">
        {/* Breadcrumbs Navigation - wrapped in Suspense for prerender compat */}
        <Suspense fallback={<div className="h-6 mb-2" />}>
          <Breadcrumbs className="mb-2" />
        </Suspense>

        {/* Page Content */}
        {children}
      </div>
    </main>
  );
}
