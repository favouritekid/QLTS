import { api } from "./client";

export interface DrillDownParams {
  metric_key: string;
  scope?: string;
  scope_officer_id?: number;
  scope_unit_id?: number;
  include_descendants?: boolean;
  from?: string;
  to?: string;
  page?: number;
  page_size?: number;
  sort_by?: string;
  order?: "asc" | "desc";
  [key: string]: unknown;
}

export interface DrillDownMetadata {
  metric_key: string;
  exactness: "exact";
  effective_scope?: {
    scope_kind: string;
    label: string;
    forced_by_role: boolean;
    includes_descendants: boolean;
  };
  effective_date_context?: {
    start_date?: string;
    end_date?: string;
  };
  page: number;
  page_size: number;
  total_count: number;
}

export interface DrillDownResponse<T = Record<string, unknown>> {
  metadata: DrillDownMetadata;
  rows: T[];
}

export const drilldownApi = {
  getConsultations: async (params: DrillDownParams) => {
    const { data } = await api.get<DrillDownResponse>("/officer/drilldowns/consultations", { params });
    return data;
  },
  getTransitions: async (params: DrillDownParams) => {
    const { data } = await api.get<DrillDownResponse>("/officer/drilldowns/transitions", { params });
    return data;
  },
  getCohorts: async (params: DrillDownParams) => {
    const { data } = await api.get<DrillDownResponse>("/officer/drilldowns/cohorts", { params });
    return data;
  },
};
