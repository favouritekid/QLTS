// src/app/(dashboard)/admin/kpi-config/_components/ConfigConflictWarnings.tsx
"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Info } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { api } from "@/lib/api/client";
import type { MetricCatalogEntry } from "@/lib/api/meta";

interface KpiConfig {
  kpi_code: string;
  period_type: string;
  unit_id: number | null;
  officer_id: number | null;
  is_active: boolean;
}

interface FormData {
  kpi_code: string;
  period_type: string;
  scope: string;
  unit_id: number | null;
  officer_id: number | null;
}

interface ConfigConflictWarningsProps {
  formData: FormData;
  isEditing: boolean;
  catalogMap: Map<string, MetricCatalogEntry>;
}

function matchesScope(config: KpiConfig, form: FormData): boolean {
  if (form.scope === "global") {
    return config.unit_id === null && config.officer_id === null;
  }
  if (form.scope === "unit") {
    return config.unit_id === form.unit_id && config.officer_id === null;
  }
  if (form.scope === "officer") {
    return config.officer_id === form.officer_id;
  }
  return false;
}

export function ConfigConflictWarnings({
  formData,
  isEditing,
  catalogMap,
}: ConfigConflictWarningsProps) {
  // Own query — always active configs, isolated from display toggle
  const { data: activeConfigs } = useQuery<KpiConfig[]>({
    queryKey: ["kpi-configs", "active-for-conflict"],
    queryFn: async () => {
      const { data } = await api.get("/api/admin/kpi-config/configs", {
        params: { is_active: true },
      });
      return data;
    },
    staleTime: 30_000,
    enabled: !isEditing && !!formData.kpi_code,
  });

  if (isEditing || !formData.kpi_code) return null;

  const entry = catalogMap.get(formData.kpi_code);

  // Warning 1: Duplicate config
  const duplicate = activeConfigs?.find(
    (c) =>
      c.kpi_code === formData.kpi_code &&
      c.period_type === formData.period_type &&
      matchesScope(c, formData)
  );

  // Warning 2: Override (global config when unit/officer configs exist)
  const hasOverride =
    formData.scope === "global" &&
    activeConfigs?.some(
      (c) =>
        c.kpi_code === formData.kpi_code &&
        (c.unit_id !== null || c.officer_id !== null)
    );

  // Warning 3: Non-comparable metric
  const isNonComparable = entry && !entry.comparison.comparable;

  return (
    <div className="space-y-2">
      {duplicate && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            Đã tồn tại cấu hình active cho KPI này với cùng phạm vi. Hệ thống
            sẽ từ chối tạo trùng.
          </AlertDescription>
        </Alert>
      )}

      {hasOverride && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Đơn vị/Cán bộ có cấu hình riêng sẽ ưu tiên dùng cấu hình đó thay
            vì Toàn cục.
          </AlertDescription>
        </Alert>
      )}

      {isNonComparable && (
        <Alert>
          <Info className="h-4 w-4" />
          <AlertDescription>
            Chỉ tiêu này chỉ hiển thị giá trị thực tế trên Dashboard, không
            hiển thị mục tiêu bên cạnh (do khác biệt phương pháp tính).
          </AlertDescription>
        </Alert>
      )}

      <p className="text-xs text-muted-foreground">
        Thứ tự ưu tiên: Cán bộ &gt; Đơn vị &gt; Toàn cục &gt; Mặc định
      </p>
    </div>
  );
}
