// src/hooks/useAdminUsers.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import { toast } from "sonner";
import type {
  User,
  UsersPage,
  AdminUserCreate,
  AdminUserUpdate,
  AdminSetPassword,
  RoleAssignment,
  BulkAction,
  ApiErrorResponse,
} from "@/types/api.types";
import { AxiosError } from "axios";

// Query key factory
export const adminUsersKeys = {
  all: ["admin", "users"] as const,
  lists: () => [...adminUsersKeys.all, "list"] as const,
  list: (filters: Record<string, unknown>) => [...adminUsersKeys.lists(), filters] as const,
  details: () => [...adminUsersKeys.all, "detail"] as const,
  detail: (id: number) => [...adminUsersKeys.details(), id] as const,
  roles: () => [...adminUsersKeys.all, "roles"] as const,
  userRoles: (id: number) => [...adminUsersKeys.roles(), id] as const,
};

// ============================================
// 📋 LIST USERS QUERY
// ============================================

interface UseAdminUsersListParams {
  page?: number;
  page_size?: number;
  search?: string;
  role?: string;
  status?: string;
  sort?: string;
  order?: "asc" | "desc";
  unit_id?: number; // Filter by organization unit
  include_children?: boolean; // Include users from child units (hierarchical filter)
}

/**
 * ✅ PHASE 1 - WEEK 2: Support initialData from Server Components
 */
export function useAdminUsersList(
  params: UseAdminUsersListParams = {},
  options?: { initialData?: UsersPage; enabled?: boolean }
) {
  const { page = 1, page_size = 10, ...filters } = params;

  return useQuery<UsersPage, AxiosError<ApiErrorResponse>>({
    queryKey: adminUsersKeys.list({ page, page_size, ...filters }),
    queryFn: async () => {
      const response = await api.get<UsersPage>(API_ENDPOINTS.ADMIN.USERS.LIST, {
        params: { page, page_size, ...filters },
      });
      return response.data;
    },
    // ✅ PERFORMANCE FIX (v17): Set staleTime to Infinity - rely on Socket.IO data_updated events
    // Data is fetched once, then only refetched when Socket.IO invalidates the cache
    staleTime: Infinity, // Never mark as stale - real-time sync via Socket.IO
    gcTime: 10 * 60 * 1000, // Garbage collect after 10 minutes of inactivity
    initialData: options?.initialData, // ✅ Use initialData from Server Component
    enabled: options?.enabled,
  });
}

// ============================================
// 👤 GET USER DETAIL QUERY
// ============================================

export function useAdminUserDetail(
  userId: number | null,
  options?: { initialData?: User }
) {
  return useQuery<User, AxiosError<ApiErrorResponse>>({
    queryKey: adminUsersKeys.detail(userId!),
    queryFn: async () => {
      const response = await api.get<User>(API_ENDPOINTS.ADMIN.USERS.DETAIL(userId!));
      return response.data;
    },
    enabled: !!userId,
    initialData: options?.initialData, // ✅ PHASE 1 - WEEK 2 - DAY 5: Support SSR
  });
}

// ============================================
// ✨ CREATE USER MUTATION
// ============================================

export function useAdminCreateUser() {
  const queryClient = useQueryClient();

  return useMutation<User, AxiosError<ApiErrorResponse>, AdminUserCreate>({
    mutationFn: async (data) => {
      const formData = new FormData();
      formData.append("username", data.username);
      formData.append("email", data.email);
      formData.append("password", data.password);
      if (data.full_name) formData.append("full_name", data.full_name);
      if (data.role) formData.append("role", data.role);
      if (data.status) formData.append("status", data.status);
      if (data.avatar) formData.append("avatar", data.avatar);

      // ✅ OPTIONAL ENHANCEMENT (Deep Dive Audit): Removed manual header setting
      // API client now auto-detects FormData and sets multipart/form-data headers
      const response = await api.post<User>(API_ENDPOINTS.ADMIN.USERS.CREATE, formData);
      return response.data;
    },
    onSuccess: () => {
      toast.success("Tạo người dùng thành công!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể tạo người dùng";
      toast.error(typeof message === "string" ? message : "Không thể tạo người dùng");
    },
  });
}

// ============================================
// 📝 UPDATE USER MUTATION
// ============================================

export function useAdminUpdateUser(userId: number) {
  const queryClient = useQueryClient();

  return useMutation<User, AxiosError<ApiErrorResponse>, AdminUserUpdate>({
    mutationFn: async (data) => {
      const formData = new FormData();
      if (data.full_name !== undefined)
        formData.append("full_name", data.full_name || "");
      if (data.email) formData.append("email", data.email);
      if (data.phone_number !== undefined)
        formData.append("phone_number", data.phone_number || "");
      if (data.role) formData.append("role", data.role);
      if (data.status) formData.append("status", data.status);
      if (data.avatar) formData.append("avatar", data.avatar);
      if (data.skills) formData.append("skills", JSON.stringify(data.skills));
      if (data.max_capacity !== undefined)
        formData.append("max_capacity", data.max_capacity.toString());
      if (data.assignment_weight !== undefined)
        formData.append("assignment_weight", data.assignment_weight.toString());
      if (data.unit_id !== undefined)
        formData.append("unit_id", (data.unit_id ?? 0).toString());

      // ✅ OPTIONAL ENHANCEMENT (Deep Dive Audit): Removed manual header setting
      // API client now auto-detects FormData and sets multipart/form-data headers
      const response = await api.put<User>(
        API_ENDPOINTS.ADMIN.USERS.UPDATE(userId),
        formData
      );
      return response.data;
    },
    onSuccess: (updatedUser) => {
      toast.success("Cập nhật người dùng thành công!");

      // ✅ PERFORMANCE FIX (v17): Use setQueriesData for surgical cache update
      // Instead of invalidating all lists (causing refetch), update the specific user in cache

      // (1) Update user in ALL list queries (handles pagination)
      queryClient.setQueriesData<{ pages: { users: User[] }[] } | { users: User[] }>(
        { queryKey: adminUsersKeys.lists() },
        (oldData) => {
          if (!oldData) return oldData;

          // Handle infinite query format (pages)
          if ("pages" in oldData) {
            const newPages = oldData.pages.map((page) => ({
              ...page,
              users: page.users.map((user) =>
                user.id === updatedUser.id ? updatedUser : user
              ),
            }));
            return { ...oldData, pages: newPages };
          }

          // Handle regular query format (flat list)
          if ("users" in oldData) {
            return {
              ...oldData,
              users: oldData.users.map((user) =>
                user.id === updatedUser.id ? updatedUser : user
              ),
            };
          }

          return oldData;
        }
      );

      // (2) Update detail cache
      queryClient.setQueryData(adminUsersKeys.detail(userId), updatedUser);

      // (3) If updated user is the current user, update auth query to refresh sidebar avatar
      const currentUser = queryClient.getQueryData<User>(["auth", "me"]);
      if (currentUser && currentUser.id === updatedUser.id) {
        queryClient.setQueryData(["auth", "me"], updatedUser);
      }

      // (4) Optional: Still invalidate statistics (they may need recalculation)
      queryClient.invalidateQueries({ queryKey: ["admin", "statistics"], refetchType: "active" });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể cập nhật người dùng";
      toast.error(typeof message === "string" ? message : "Không thể cập nhật người dùng");
    },
  });
}

// ============================================
// 🗑️ DELETE USER MUTATION
// ============================================

export function useAdminDeleteUser() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (userId) => {
      await api.delete(API_ENDPOINTS.ADMIN.USERS.DELETE(userId));
    },
    onSuccess: () => {
      toast.success("Xoá người dùng thành công!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể xoá người dùng";
      toast.error(typeof message === "string" ? message : "Không thể xoá người dùng");
    },
  });
}

// ============================================
// 🔑 ADMIN SET PASSWORD MUTATION
// ============================================

export function useAdminSetPassword(userId: number) {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, AdminSetPassword>({
    mutationFn: async (data) => {
      await api.post(API_ENDPOINTS.ADMIN.USERS.SET_PASSWORD(userId), data);
    },
    onSuccess: () => {
      toast.success("Đặt mật khẩu thành công!");
      // Refresh password_reset_required flag trong detail page
      queryClient.invalidateQueries({
        queryKey: adminUsersKeys.detail(userId),
        refetchType: "active",
      });
      // Refresh list (status badge có thể thay đổi)
      queryClient.invalidateQueries({
        queryKey: adminUsersKeys.lists(),
        refetchType: "active",
      });
      // Nếu là current user → invalidate auth cache
      const currentUser = queryClient.getQueryData<User>(["auth", "me"]);
      if (currentUser && currentUser.id === userId) {
        queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      }
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể đặt mật khẩu";
      toast.error(typeof message === "string" ? message : "Không thể đặt mật khẩu");
    },
  });
}

// ============================================
// 👔 ASSIGN ROLE MUTATION
// ============================================

export function useAdminAssignRole() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, RoleAssignment>({
    mutationFn: async (data) => {
      await api.post(API_ENDPOINTS.ADMIN.PERMISSIONS.ASSIGN_ROLE, data);
    },
    onSuccess: (_, variables) => {
      toast.success("Gán vai trò thành công!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists(), refetchType: "active" });
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.userRoles(variables.user_id), refetchType: "active" });
      // Nếu role thay đổi của chính current user → cần invalidate auth cache
      const currentUser = queryClient.getQueryData<User>(["auth", "me"]);
      if (currentUser && currentUser.id === variables.user_id) {
        queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      }
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể gán vai trò";
      toast.error(typeof message === "string" ? message : "Không thể gán vai trò");
    },
  });
}

// ============================================
// 👔 REMOVE ROLE MUTATION
// ============================================

export function useAdminRemoveRole() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, RoleAssignment>({
    mutationFn: async (data) => {
      // THU HỒI đi đường RIÊNG (`DELETE /api/admin/roles/revoke`), không phải
      // đường gán với method khác. Dùng lại `ASSIGN_ROLE` ở đây là cách hai
      // hành động ngược nhau bị buộc vào một hằng số.
      await api.delete(API_ENDPOINTS.ADMIN.PERMISSIONS.REVOKE_ROLE, { data });
    },
    onSuccess: (_, variables) => {
      toast.success("Xoá vai trò thành công!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists(), refetchType: "active" });
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.userRoles(variables.user_id), refetchType: "active" });
      // Nếu role thay đổi của chính current user → cần invalidate auth cache
      const currentUser = queryClient.getQueryData<User>(["auth", "me"]);
      if (currentUser && currentUser.id === variables.user_id) {
        queryClient.invalidateQueries({ queryKey: ["auth", "me"] });
      }
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể xoá vai trò";
      toast.error(typeof message === "string" ? message : "Không thể xoá vai trò");
    },
  });
}

// ============================================
// 📦 BULK ACTION MUTATION
// ============================================

export function useAdminBulkAction() {
  const queryClient = useQueryClient();

  return useMutation<{ detail: string }, AxiosError<ApiErrorResponse>, BulkAction>({
    mutationFn: async (data) => {
      const response = await api.post<{ detail: string }>(
        API_ENDPOINTS.ADMIN.USERS.BULK_ACTION,
        data
      );
      return response.data;
    },
    onSuccess: (data) => {
      toast.success(data.detail || "Thao tác hàng loạt thành công!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Không thể thực hiện thao tác hàng loạt";
      toast.error(typeof message === "string" ? message : "Không thể thực hiện thao tác hàng loạt");
    },
  });
}

// ============================================
// 👔 GET USER ROLES QUERY
// ============================================

export function useAdminUserRoles(userId: number) {
  return useQuery<string[], AxiosError<ApiErrorResponse>>({
    queryKey: adminUsersKeys.userRoles(userId),
    queryFn: async () => {
      const response = await api.get<string[]>(API_ENDPOINTS.ADMIN.USERS.ROLES(userId));
      return response.data;
    },
    enabled: !!userId,
    staleTime: 0, // Always fetch fresh roles
    refetchOnMount: true, // Refetch when dialog opens
  });
}
// ============================================
// 👔 ASSIGN/UNASSIGN UNIT MUTATIONS
// ============================================

import { masterDataApi } from "@/lib/api/master-data";



export function useAssignUserToUnit() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, unitId }: { userId: number; unitId: number }) => {
      return masterDataApi.assignUserToUnit(userId, unitId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
      toast.success("Gán người dùng vào đơn vị thành công");
    },
    onError: () => {
      toast.error("Không thể gán người dùng vào đơn vị");
    },
  });
}

export function useUnassignUserFromUnit() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ userId, unitId }: { userId: number; unitId: number }) => {
      return masterDataApi.unassignUserFromUnit(userId, unitId);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
      toast.success("Gỡ người dùng khỏi đơn vị thành công");
    },
    onError: () => {
      toast.error("Không thể gỡ người dùng khỏi đơn vị");
    },
  });
}
