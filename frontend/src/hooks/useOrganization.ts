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
  MajorAcademicInfo,
  MajorAcademicInfoCreate,
  MajorAcademicInfoUpdate,
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

  // Unit types
  unitTypes: () => [...organizationKeys.all, "unitTypes"] as const,

  // Major-specific keys
  majors: () => [...organizationKeys.all, "majors"] as const,
  majorsList: (unitId?: number, search?: string) =>
    [...organizationKeys.majors(), { unitId, search }] as const,
  majorDetail: (id: number) => [...organizationKeys.majors(), "detail", id] as const,

  // Academic Info keys
  academicInfo: () => [...organizationKeys.all, "academicInfo"] as const,
  academicInfoHistory: (majorId: number, publishedOnly?: boolean) =>
    [...organizationKeys.academicInfo(), "history", majorId, { publishedOnly }] as const,
  academicInfoByYear: (majorId: number, year: number) =>
    [...organizationKeys.academicInfo(), "year", majorId, year] as const,
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
 * Get allowed organization unit types
 * Uses: Public endpoint, cached for 24 hours (rarely changes)
 */
export function useOrganizationUnitTypes() {
  return useQuery<string[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.unitTypes(),
    queryFn: async () => {
      const response = await api.get<string[]>(
        API_ENDPOINTS.ORGANIZATION.UNIT_TYPES
      );
      return response.data;
    },
    staleTime: 1000 * 60 * 60 * 24, // 24 hours
    gcTime: 1000 * 60 * 60 * 24, // 24 hours
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

/**
 * Get academic info history for a major
 */
export function useAcademicInfoHistory(majorId: number, publishedOnly: boolean = false) {
  return useQuery<MajorAcademicInfo[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.academicInfoHistory(majorId, publishedOnly),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (publishedOnly) params.append("published_only", "true");

      const response = await api.get<MajorAcademicInfo[]>(
        `${API_ENDPOINTS.ORGANIZATION.ACADEMIC_INFO_HISTORY(majorId)}?${params.toString()}`
      );
      return response.data;
    },
    enabled: !!majorId,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

/**
 * Get academic info for a specific year
 */
export function useAcademicInfoByYear(majorId: number, year: number) {
  return useQuery<MajorAcademicInfo, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.academicInfoByYear(majorId, year),
    queryFn: async () => {
      const response = await api.get<MajorAcademicInfo>(
        API_ENDPOINTS.ORGANIZATION.ACADEMIC_INFO_BY_YEAR(majorId, year)
      );
      return response.data;
    },
    enabled: !!majorId && !!year,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - Organization Units
// =====================================================================

/**
 * Create a new organization unit
 */
export function useCreateUnit() {
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
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Tạo đơn vị thất bại";
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
    { id: number; data: OrganizationUnitUpdate },
    { previousUnits: OrganizationUnit[] | undefined }
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

      const detail = err.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Cập nhật đơn vị thất bại";
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
  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_UNIT(id));
    },

    onSuccess: () => {
      toast.success("Đơn vị đã được xóa!");
      // Socket.IO will handle cache invalidation
    },

    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Xóa đơn vị thất bại";
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
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Tạo ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing major
 */
export function useUpdateMajor() {
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
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Cập nhật ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Delete a major
 */
export function useDeleteMajor() {
  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_MAJOR(id));
    },
    onSuccess: () => {
      toast.success("Ngành học đã được xóa!");
      // Socket.IO will handle cache invalidation
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Xóa ngành học thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - Academic Info
// =====================================================================

/**
 * Create new academic info for a major
 */
export function useCreateAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation<
    MajorAcademicInfo,
    AxiosError<ApiErrorResponse>,
    MajorAcademicInfoCreate
  >({
    mutationFn: async (data) => {
      const response = await api.post<MajorAcademicInfo>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_ACADEMIC_INFO(data.major_id),
        data
      );
      return response.data;
    },
    onSuccess: (newInfo) => {
      toast.success("Thông tin học thuật đã được tạo!", {
        description: `Năm học ${newInfo.academic_year}`,
      });
      // Invalidate history query
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoHistory(newInfo.major_id),
      });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Tạo thông tin học thuật thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update existing academic info
 */
export function useUpdateAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation<
    MajorAcademicInfo,
    AxiosError<ApiErrorResponse>,
    { id: number; data: MajorAcademicInfoUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.patch<MajorAcademicInfo>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_ACADEMIC_INFO(id),
        data
      );
      return response.data;
    },
    onSuccess: (updatedInfo) => {
      toast.success("Thông tin học thuật đã được cập nhật!", {
        description: `Năm học ${updatedInfo.academic_year}`,
      });
      // Invalidate history and specific year queries
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoHistory(updatedInfo.major_id),
      });
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoByYear(updatedInfo.major_id, updatedInfo.academic_year),
      });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Cập nhật thông tin học thuật thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Delete academic info
 */
export function useDeleteAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    { id: number; majorId: number }
  >({
    mutationFn: async ({ id }) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_ACADEMIC_INFO(id));
    },
    onSuccess: (_, variables) => {
      toast.success("Thông tin học thuật đã được xóa!");
      // Invalidate history query
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoHistory(variables.majorId),
      });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Xóa thông tin học thuật thất bại";
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
