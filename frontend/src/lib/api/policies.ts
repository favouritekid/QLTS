import { api } from "./client";
import { API_ENDPOINTS } from "./endpoints";

const PERMISSIONS = API_ENDPOINTS.ADMIN.PERMISSIONS;
const SYNC = API_ENDPOINTS.ADMIN.SYNC;

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
    const response = await api.get<RoleFeaturesResponse>(PERMISSIONS.ROLE_FEATURES(role));
    return response.data;
  },

  toggleFeature: async (role: string, featureId: string, enabled: boolean) => {
    const response = await api.post(PERMISSIONS.TOGGLE_FEATURE(role), {
      feature_id: featureId,
      enabled,
    });
    return response.data;
  },

  // Permission Lookup & Simulation
  //
  // ⚠️ `who-can-access` là **POST** (roles.py:1336), không phải GET — bản cũ gọi
  // GET vào một đường không tồn tại nên hỏng hai lần cùng lúc.
  // Nhưng backend khai `object`/`action` bằng `Query(...)`, nên chúng vẫn phải
  // đi ở QUERY STRING: đối số thứ ba `config.params`. Đối số thứ hai (body) cố ý
  // để `undefined` — nhét chúng vào JSON body sẽ khiến FastAPI trả 422 vì hai
  // query bắt buộc bị thiếu, một lỗi trông giống hệt "backend hỏng".
  lookupPermissions: async (object: string, action: string) => {
    const response = await api.post<LookupResult>(PERMISSIONS.WHO_CAN_ACCESS, undefined, {
      params: { object, action },
    });
    return response.data;
  },

  simulatePermission: async (data: { subject: string; object: string; action: string }) => {
    const response = await api.post<SimulationResult>(PERMISSIONS.SIMULATE, data);
    return response.data;
  },

  // Sync — router RIÊNG `/api/admin/sync`, không thuộc cụm `/roles`.
  getSyncStatus: async () => {
    const response = await api.get<SyncStatus>(SYNC.STATUS);
    return response.data;
  },

  // `syncPolicies` (POST /api/admin/policies/sync) đã được GỠ: không router nào
  // phục vụ đường đó và không nơi nào trong `src/` gọi nó. Giữ lại một hàm chết
  // trỏ vào 404 chỉ tạo nguy cơ có người "dùng thử" rồi tưởng backend hỏng.
  syncUsers: async (userIds: number[] | null) => {
    const response = await api.post<SyncResult>(SYNC.RUN, {
      user_ids: userIds,
    });
    return response.data;
  },
};
