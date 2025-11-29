// src/components/layouts/dashboard/Main.tsx
"use client";

import { cn } from "@/lib/utils";
import React from "react";
import { Breadcrumbs } from "@/components/common/Breadcrumbs";

export function Main({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <main
      className={cn(
        // Padding và spacing - Padding sẽ tạo khoảng cách xung quanh content
        "flex-1 p-3 md:p-4 lg:p-6",
        // Overflow control
        "overflow-x-hidden overflow-y-auto",
        // Min height để đảm bảo chiếm toàn bộ viewport
        "min-h-[calc(100vh-3.5rem)]",
        className
      )}
    >
      {/* Container với max-width và spacing */}
      <div className="mx-auto w-full max-w-[1600px] space-y-4">
        {/* Breadcrumbs Navigation */}
        <Breadcrumbs className="mb-2" />

        {/* Page Content */}
        {children}
      </div>
    </main>
  );
}
