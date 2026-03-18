// src/app/(dashboard)/admin/kpi-config/_components/KpiWorkflowStepper.tsx
"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const STEPS: { label: string; href: string; current?: boolean }[] = [
  { label: "Kế hoạch KPI", href: "/admin/kpi-planning" },
  { label: "Cấu hình chỉ tiêu", href: "/admin/kpi-config", current: true },
  { label: "Kiểm tra độ phủ", href: "/admin/kpi-setup" },
];

export function KpiWorkflowStepper() {
  return (
    <nav
      aria-label="KPI setup workflow"
      className="scrollbar-hide flex items-center gap-1 overflow-x-auto rounded-lg border bg-muted/50 px-4 py-2"
    >
      {STEPS.map((step, i) => (
        <div key={step.href} className="flex items-center gap-1">
          {i > 0 && (
            <ChevronRight className="h-4 w-4 flex-shrink-0 text-muted-foreground" />
          )}
          {step.current ? (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground whitespace-nowrap">
              <span className="flex h-4 w-4 items-center justify-center rounded-full bg-primary-foreground/20 text-[10px] font-bold">
                {i + 1}
              </span>
              {step.label}
            </span>
          ) : (
            <Link
              href={step.href}
              className="inline-flex items-center gap-1.5 rounded-md px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground whitespace-nowrap"
            >
              <span className="flex h-4 w-4 items-center justify-center rounded-full border text-[10px]">
                {i + 1}
              </span>
              {step.label}
            </Link>
          )}
        </div>
      ))}
    </nav>
  );
}
