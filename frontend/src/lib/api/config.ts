import { api } from "./client";
import { ConfigSystemCategory } from "../zod/config";

export const configApi = {
  getCategories: async (type: string) => {
    const { data } = await api.get<ConfigSystemCategory[]>(`/api/config/categories`, {
        params: { type }
    });
    return data;
  }
};
