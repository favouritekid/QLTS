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
}

export function useAdminUsersList(params: UseAdminUsersListParams = {}) {
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
  });
}

// ============================================
// 👤 GET USER DETAIL QUERY
// ============================================

export function useAdminUserDetail(userId: number | null) {
  return useQuery<User, AxiosError<ApiErrorResponse>>({
    queryKey: adminUsersKeys.detail(userId!),
    queryFn: async () => {
      const response = await api.get<User>(API_ENDPOINTS.ADMIN.USERS.DETAIL(userId!));
      return response.data;
    },
    enabled: !!userId,
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

      const response = await api.post<User>(API_ENDPOINTS.ADMIN.USERS.CREATE, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return response.data;
    },
    onSuccess: () => {
      toast.success("User created successfully!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to create user";
      toast.error(typeof message === "string" ? message : "Failed to create user");
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

      const response = await api.put<User>(
        API_ENDPOINTS.ADMIN.USERS.UPDATE(userId),
        formData,
        {
          headers: { "Content-Type": "multipart/form-data" },
        }
      );
      return response.data;
    },
    onSuccess: (updatedUser) => {
      toast.success("User updated successfully!");

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
      const message = error.response?.data?.detail || "Failed to update user";
      toast.error(typeof message === "string" ? message : "Failed to update user");
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
      toast.success("User deleted successfully!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to delete user";
      toast.error(typeof message === "string" ? message : "Failed to delete user");
    },
  });
}

// ============================================
// 🔑 ADMIN SET PASSWORD MUTATION
// ============================================

export function useAdminSetPassword(userId: number) {
  return useMutation<void, AxiosError<ApiErrorResponse>, AdminSetPassword>({
    mutationFn: async (data) => {
      await api.post(API_ENDPOINTS.ADMIN.USERS.SET_PASSWORD(userId), data);
    },
    onSuccess: () => {
      toast.success("Password updated successfully!");
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to set password";
      toast.error(typeof message === "string" ? message : "Failed to set password");
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
      toast.success("Role assigned successfully!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists(), refetchType: "active" });
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.userRoles(variables.user_id), refetchType: "active" });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to assign role";
      toast.error(typeof message === "string" ? message : "Failed to assign role");
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
      await api.delete(API_ENDPOINTS.ADMIN.PERMISSIONS.ASSIGN_ROLE, { data });
    },
    onSuccess: (_, variables) => {
      toast.success("Role removed successfully!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists(), refetchType: "active" });
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.userRoles(variables.user_id), refetchType: "active" });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to remove role";
      toast.error(typeof message === "string" ? message : "Failed to remove role");
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
      toast.success(data.detail || "Bulk action completed successfully!");
      queryClient.invalidateQueries({ queryKey: adminUsersKeys.lists() });
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Failed to perform bulk action";
      toast.error(typeof message === "string" ? message : "Failed to perform bulk action");
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
