import { api } from "./client";

export interface RoleFeaturesResponse {
  role: string;
  features: FeatureStatus[];
}

export interface FeatureStatus {
  feature_id: string;
  display_name: string;
  enabled: boolean;
  policy_count: number;
}

export interface LookupResult {
  object: string;
  action: string;
  allowed_subjects: string[];
  total_count: number;
}

export interface SimulationResult {
  subject: string;
  object: string;
  action: string;
  is_allowed: boolean;
  message: string;
}

export interface MismatchedUser {
  user_id: number;
  username: string;
  db_role: string;
  casbin_role: string;
  all_casbin_roles: string[];
}

export interface SyncStatus {
  total_users: number;
  synced_count: number;
  out_of_sync_count: number;
  mismatched_users: MismatchedUser[];
  last_synced_at?: string; // Keep this just in case, or make optional
}

export interface SyncResult {
  synced_count: number;
  failed_count: number;
}

export const policiesApi = {
  // Feature Policies
  getRoleFeatures: async (role: string) => {
    const response = await api.get<RoleFeaturesResponse>(`/api/admin/roles/${role}/features`);
    return response.data;
  },

  toggleFeature: async (role: string, featureId: string, enabled: boolean) => {
    const response = await api.post(`/api/admin/roles/${role}/features/toggle`, {
      feature_id: featureId,
      enabled,
    });
    return response.data;
  },

  // Permission Lookup & Simulation
  lookupPermissions: async (object: string, action: string) => {
    const response = await api.get<LookupResult>("/api/admin/policies/who-can-access", {
      params: { object, action },
    });
    return response.data;
  },

  simulatePermission: async (data: { subject: string; object: string; action: string }) => {
    const response = await api.post<SimulationResult>("/api/admin/policies/simulate", data);
    return response.data;
  },

  // Sync
  getSyncStatus: async () => {
    const response = await api.get<SyncStatus>("/api/admin/policies/sync-status");
    return response.data;
  },
  
  syncPolicies: async () => {
    const response = await api.post("/api/admin/policies/sync");
    return response.data;
  },

  syncUsers: async (userIds: number[] | null) => {
    const response = await api.post<{ synced_count: number; failed_count: number }>("/api/admin/sync/users", {
      user_ids: userIds,
    });
    return response.data;
  },
};
