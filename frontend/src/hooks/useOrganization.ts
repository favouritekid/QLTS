// src/hooks/useOrganization.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { ApiErrorResponse } from "@/types/api.types";
import type {
  OrganizationUnit,
  OrganizationUnitCreate,
  OrganizationUnitUpdate,
  Major,
  MajorCreate,
  MajorUpdate,
} from "@/types/organization.types";

// =====================================================================
// QUERY KEYS
// =====================================================================

export const organizationKeys = {
  all: ["organization"] as const,
  lists: () => [...organizationKeys.all, "list"] as const,
  list: (filters?: string) => [...organizationKeys.lists(), { filters }] as const,
  details: () => [...organizationKeys.all, "detail"] as const,
  detail: (id: number) => [...organizationKeys.details(), id] as const,

  // Major-specific keys
  majors: () => [...organizationKeys.all, "majors"] as const,
  majorsList: (unitId?: number, search?: string) =>
    [...organizationKeys.majors(), { unitId, search }] as const,
  majorDetail: (id: number) => [...organizationKeys.majors(), "detail", id] as const,
};

// =====================================================================
// QUERIES (READ)
// =====================================================================

/**
 * Get all organization units (tree structure)
 * Uses: Public endpoint, automatic cache invalidation via Socket.IO
 */
export function useOrganizationUnits() {
  return useQuery<OrganizationUnit[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.list(),
    queryFn: async () => {
      const response = await api.get<OrganizationUnit[]>(
        API_ENDPOINTS.ORGANIZATION.LIST_UNITS
      );
      return response.data;
    },
    staleTime: Infinity, // Cache forever, invalidate via Socket.IO
    gcTime: 1000 * 60 * 30, // 30 minutes in cache
  });
}

/**
 * Get a single organization unit by ID
 */
export function useOrganizationUnit(id: number) {
  return useQuery<OrganizationUnit, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.detail(id),
    queryFn: async () => {
      const response = await api.get<OrganizationUnit>(
        API_ENDPOINTS.ORGANIZATION.GET_UNIT(id)
      );
      return response.data;
    },
    enabled: !!id,
    staleTime: Infinity,
  });
}

/**
 * Get majors by unit ID (with optional search)
 */
export function useMajors(unitId?: number, search?: string) {
  return useQuery<Major[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.majorsList(unitId, search),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (unitId) params.append("unitId", String(unitId));
      if (search) params.append("search", search);

      const response = await api.get<Major[]>(
        `${API_ENDPOINTS.ORGANIZATION.LIST_MAJORS}?${params.toString()}`
      );
      return response.data;
    },
    enabled: !!unitId,
    staleTime: Infinity,
  });
}

/**
 * Get a single major by ID
 */
export function useMajor(id: number) {
  return useQuery<Major, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.majorDetail(id),
    queryFn: async () => {
      const response = await api.get<Major>(
        API_ENDPOINTS.ORGANIZATION.GET_MAJOR(id)
      );
      return response.data;
    },
    enabled: !!id,
    staleTime: Infinity,
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - Organization Units
// =====================================================================

/**
 * Create a new organization unit
 */
export function useCreateUnit() {
  const queryClient = useQueryClient();

  return useMutation<
    OrganizationUnit,
    AxiosError<ApiErrorResponse>,
    OrganizationUnitCreate
  >({
    mutationFn: async (data) => {
      const response = await api.post<OrganizationUnit>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_UNIT,
        data
      );
      return response.data;
    },
    onSuccess: (newUnit) => {
      toast.success("Đơn vị mới đã được tạo!", {
        description: newUnit.name,
      });
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Tạo đơn vị thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing organization unit
 * Includes optimistic updates
 */
export function useUpdateUnit() {
  const queryClient = useQueryClient();

  return useMutation<
    OrganizationUnit,
    AxiosError<ApiErrorResponse>,
    { id: number; data: OrganizationUnitUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put<OrganizationUnit>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_UNIT(id),
        data
      );
      return response.data;
    },

    // Optimistic update
    onMutate: async ({ id, data }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: organizationKeys.list() });

      // Snapshot the previous value
      const previousUnits = queryClient.getQueryData<OrganizationUnit[]>(
        organizationKeys.list()
      );

      // Optimistically update the cache
      if (previousUnits) {
        const updateUnitInTree = (units: OrganizationUnit[]): OrganizationUnit[] => {
          return units.map(unit => {
            if (unit.id === id) {
              return { ...unit, ...data };
            }
            if (unit.children && unit.children.length > 0) {
              return {
                ...unit,
                children: updateUnitInTree(unit.children)
              };
            }
            return unit;
          });
        };

        queryClient.setQueryData<OrganizationUnit[]>(
          organizationKeys.list(),
          updateUnitInTree(previousUnits)
        );
      }

      return { previousUnits };
    },

    // Rollback on error
    onError: (err, variables, context) => {
      if (context?.previousUnits) {
        queryClient.setQueryData(
          organizationKeys.list(),
          context.previousUnits
        );
      }

      const message = err.response?.data?.detail || "Cập nhật đơn vị thất bại";
      toast.error("Lỗi", { description: message });
    },

    onSuccess: (updatedUnit) => {
      toast.success("Đơn vị đã được cập nhật!", {
        description: updatedUnit.name,
      });
      // Socket.IO will handle final cache invalidation
    },
  });
}

/**
 * Delete an organization unit
 */
export function useDeleteUnit() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_UNIT(id));
    },

    onSuccess: () => {
      toast.success("Đơn vị đã được xóa!");
      // Socket.IO will handle cache invalidation
    },

    onError: (error) => {
      const message = error.response?.data?.detail || "Xóa đơn vị thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - Majors
// =====================================================================

/**
 * Create a new major
 */
export function useCreateMajor() {
  const queryClient = useQueryClient();

  return useMutation<Major, AxiosError<ApiErrorResponse>, MajorCreate>({
    mutationFn: async (data) => {
      const response = await api.post<Major>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_MAJOR,
        data
      );
      return response.data;
    },
    onSuccess: (newMajor) => {
      toast.success("Ngành học mới đã được tạo!", {
        description: newMajor.name,
      });
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Tạo ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing major
 */
export function useUpdateMajor() {
  const queryClient = useQueryClient();

  return useMutation<
    Major,
    AxiosError<ApiErrorResponse>,
    { id: number; data: MajorUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put<Major>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_MAJOR(id),
        data
      );
      return response.data;
    },
    onSuccess: (updatedMajor) => {
      toast.success("Ngành học đã được cập nhật!", {
        description: updatedMajor.name,
      });
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Cập nhật ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Delete a major
 */
export function useDeleteMajor() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_MAJOR(id));
    },
    onSuccess: () => {
      toast.success("Ngành học đã được xóa!");
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const message = error.response?.data?.detail || "Xóa ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// UTILITY FUNCTIONS
// =====================================================================

/**
 * Flatten organization tree for easier rendering
 * Preserves hierarchy information
 */
export function flattenOrganizationTree(
  units: OrganizationUnit[],
  level: number = 0
): Array<{ unit: OrganizationUnit; level: number; hasChildren: boolean }> {
  const result: Array<{ unit: OrganizationUnit; level: number; hasChildren: boolean }> = [];

  for (const unit of units) {
    result.push({
      unit,
      level,
      hasChildren: unit.children && unit.children.length > 0,
    });

    if (unit.children && unit.children.length > 0) {
      result.push(...flattenOrganizationTree(unit.children, level + 1));
    }
  }

  return result;
}

/**
 * Get all descendant IDs of a unit (for preventing circular dependencies)
 */
export function getAllDescendantIds(
  unit: OrganizationUnit,
  allUnits: OrganizationUnit[]
): Set<number> {
  const descendants = new Set<number>([unit.id]);

  const findChildren = (parentId: number) => {
    const children = allUnits.filter(u => u.parent_id === parentId);
    children.forEach(child => {
      descendants.add(child.id);
      findChildren(child.id); // Recursive
    });
  };

  findChildren(unit.id);
  return descendants;
}

/**
 * Check if making unitId a parent of childId would create a circular dependency
 */
export function wouldCreateCircularDependency(
  parentId: number,
  childId: number,
  allUnits: OrganizationUnit[]
): boolean {
  const childUnit = allUnits.find(u => u.id === childId);
  if (!childUnit) return false;

  const descendants = getAllDescendantIds(childUnit, allUnits);
  return descendants.has(parentId);
}
