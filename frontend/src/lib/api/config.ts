import { api } from "./client";
import { ConfigSystemCategory } from "../zod/config";

// Types
export interface SubjectGroup {
  id: number;
  code: string;
  name: string;
  subjects: string[];
  display_order: number;
  is_active: boolean;
}

export const configApi = {
  getCategories: async (type: string) => {
    const { data } = await api.get<ConfigSystemCategory[]>(`/api/config/categories`, {
        params: { type }
    });
    return data;
  },

  // Subject Groups API (Phase 6: Dynamic Admission Scoring)
  getSubjectGroups: async () => {
    const { data } = await api.get<SubjectGroup[]>(`/api/config/subject-groups`);
    return data;
  },

  getSubjectGroupByCode: async (code: string) => {
    const { data } = await api.get<SubjectGroup>(`/api/config/subject-groups/${code}`);
    return data;
  },
};
