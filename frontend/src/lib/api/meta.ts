// src/lib/api/meta.ts
import { api } from "./client";

export interface ComparisonPolicy {
  comparable: boolean;
  requires_period_match: boolean;
  target_period: string | null;
  caveat: string | null;
}

export interface MetricCatalogEntry {
  code: string;
  display_name: string;
  unit: "count" | "percent" | "hours";
  period_type: "daily" | "monthly" | "annual";
  default_value: number;
  higher_is_better: boolean;
  actual_kind: string;
  comparison: ComparisonPolicy;
  display_aliases: {
    dashboard: string;
    planning: string;
    config: string;
    annual_progress: string;
  };
}

export const metaApi = {
  getKpiCatalog: async (): Promise<MetricCatalogEntry[]> => {
    const { data } = await api.get<MetricCatalogEntry[]>("/api/meta/kpi-catalog");
    return data;
  },
};
