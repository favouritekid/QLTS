// src/hooks/useOrganization.ts
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AxiosError } from "axios";
import { toast } from "sonner";
import { api } from "@/lib/api/client";
import { API_ENDPOINTS } from "@/lib/api/endpoints";
import type { ApiErrorResponse } from "@/types/api.types";
import type {
  // Organization Units
  OrganizationUnit,
  OrganizationUnitCreate,
  OrganizationUnitUpdate,
  OrganizationTreeNodeWithAggregation,

  // 3-Tier Architecture (NEW)
  MajorProgram,
  MajorProgramCreate,
  MajorProgramUpdate,
  ProgramOffering,
  ProgramOfferingCreate,
  ProgramOfferingUpdate,
  OfferingAcademicInfo,
  OfferingAcademicInfoCreate,
  OfferingAcademicInfoUpdate,

  // System Configuration
  ConfigDegreeLevel,
  ConfigOfferingType,

  // Legacy (Deprecated)
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

  // Tree with aggregation
  treeWithAggregation: (academicYear?: number, includeInactive?: boolean) =>
    [...organizationKeys.all, "treeWithAggregation", { academicYear, includeInactive }] as const,

  // === 3-TIER ARCHITECTURE KEYS (NEW) ===
  // Tier 1: MajorProgram
  majorPrograms: () => [...organizationKeys.all, "majorPrograms"] as const,
  majorProgramsList: (unitId?: number, search?: string) =>
    [...organizationKeys.majorPrograms(), "list", { unitId, search }] as const,
  majorProgramDetail: (id: number) => [...organizationKeys.majorPrograms(), "detail", id] as const,

  // Tier 2: ProgramOffering
  offerings: () => [...organizationKeys.all, "offerings"] as const,
  offeringsList: (programId: number) =>
    [...organizationKeys.offerings(), "list", programId] as const,
  offeringDetail: (id: number) => [...organizationKeys.offerings(), "detail", id] as const,
  offeringCurrentInfo: (id: number) => [...organizationKeys.offerings(), "currentInfo", id] as const,

  // Tier 3: OfferingAcademicInfo
  academicInfo: () => [...organizationKeys.all, "academicInfo"] as const,
  academicInfoList: (offeringId: number, publishedOnly?: boolean) =>
    [...organizationKeys.academicInfo(), "list", offeringId, { publishedOnly }] as const,
  academicInfoByYear: (offeringId: number, year: number) =>
    [...organizationKeys.academicInfo(), "year", offeringId, year] as const,

  // === LEGACY KEYS (DEPRECATED) ===
  majors: () => [...organizationKeys.all, "majors"] as const,
  majorsList: (unitId?: number, search?: string) =>
    [...organizationKeys.majors(), { unitId, search }] as const,
  majorDetail: (id: number) => [...organizationKeys.majors(), "detail", id] as const,
  academicInfoHistory: (majorId: number, publishedOnly?: boolean) =>
    [...organizationKeys.all, "legacyAcademicInfo", "history", majorId, { publishedOnly }] as const,
  academicInfoByYearLegacy: (majorId: number, year: number) =>
    [...organizationKeys.all, "legacyAcademicInfo", "year", majorId, year] as const,
};

// =====================================================================
// QUERIES (READ) - ORGANIZATION UNITS
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
 * Get organization tree with majors and aggregated statistics
 * @param academicYear - Academic year to fetch data for (defaults to current year)
 * @param includeInactive - Whether to include inactive units (default: false)
 */
export function useOrganizationTreeWithAggregation(
  academicYear?: number,
  includeInactive: boolean = false
) {
  return useQuery<OrganizationTreeNodeWithAggregation[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.treeWithAggregation(academicYear, includeInactive),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (academicYear) params.append("academic_year", academicYear.toString());
      if (includeInactive) params.append("include_inactive", "true");

      const url = `${API_ENDPOINTS.ORGANIZATION.TREE_WITH_AGGREGATION}${
        params.toString() ? `?${params.toString()}` : ""
      }`;

      const response = await api.get<OrganizationTreeNodeWithAggregation[]>(url);
      return response.data;
    },
    staleTime: 1000 * 60 * 5, // 5 minutes (data can change)
    gcTime: 1000 * 60 * 10, // 10 minutes in cache
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

// =====================================================================
// QUERIES (READ) - TIER 1: MAJOR PROGRAM
// =====================================================================

/**
 * Get all major programs (with optional filters)
 */
export function useMajorPrograms(unitId?: number, search?: string) {
  return useQuery<MajorProgram[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.majorProgramsList(unitId, search),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (unitId) params.append("unit_id", String(unitId));
      if (search) params.append("search", search);

      const response = await api.get<MajorProgram[]>(
        `${API_ENDPOINTS.ORGANIZATION.LIST_MAJOR_PROGRAMS}${
          params.toString() ? `?${params.toString()}` : ""
        }`
      );
      return response.data;
    },
    staleTime: Infinity,
  });
}

/**
 * Get a single major program by ID
 */
export function useMajorProgram(id: number) {
  return useQuery<MajorProgram, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.majorProgramDetail(id),
    queryFn: async () => {
      const response = await api.get<MajorProgram>(
        API_ENDPOINTS.ORGANIZATION.GET_MAJOR_PROGRAM(id)
      );
      return response.data;
    },
    enabled: !!id,
    staleTime: Infinity,
  });
}

// =====================================================================
// QUERIES (READ) - TIER 2: PROGRAM OFFERING
// =====================================================================

/**
 * Get all offerings for a major program
 */
export function useProgramOfferings(programId: number) {
  return useQuery<ProgramOffering[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.offeringsList(programId),
    queryFn: async () => {
      const response = await api.get<ProgramOffering[]>(
        API_ENDPOINTS.ORGANIZATION.LIST_OFFERINGS(programId)
      );
      return response.data;
    },
    enabled: !!programId,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

/**
 * Get a single offering by ID
 */
export function useProgramOffering(id: number) {
  return useQuery<ProgramOffering, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.offeringDetail(id),
    queryFn: async () => {
      const response = await api.get<ProgramOffering>(
        API_ENDPOINTS.ORGANIZATION.GET_OFFERING(id)
      );
      return response.data;
    },
    enabled: !!id,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

/**
 * Get current academic info for an offering (current year + published)
 */
export function useOfferingCurrentInfo(id: number) {
  return useQuery<OfferingAcademicInfo, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.offeringCurrentInfo(id),
    queryFn: async () => {
      const response = await api.get<OfferingAcademicInfo>(
        API_ENDPOINTS.ORGANIZATION.GET_OFFERING_CURRENT_INFO(id)
      );
      return response.data;
    },
    enabled: !!id,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

// =====================================================================
// QUERIES (READ) - TIER 3: OFFERING ACADEMIC INFO
// =====================================================================

/**
 * Get academic info history for an offering
 */
export function useOfferingAcademicInfoList(
  offeringId: number,
  publishedOnly: boolean = false
) {
  return useQuery<OfferingAcademicInfo[], AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.academicInfoList(offeringId, publishedOnly),
    queryFn: async () => {
      const params = new URLSearchParams();
      if (publishedOnly) params.append("published_only", "true");

      const response = await api.get<OfferingAcademicInfo[]>(
        `${API_ENDPOINTS.ORGANIZATION.LIST_ACADEMIC_INFO(offeringId)}${
          params.toString() ? `?${params.toString()}` : ""
        }`
      );
      return response.data;
    },
    enabled: !!offeringId,
    staleTime: 1000 * 60 * 5, // 5 minutes
  });
}

/**
 * Get academic info for a specific year
 */
export function useOfferingAcademicInfoByYear(offeringId: number, year: number) {
  return useQuery<OfferingAcademicInfo, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.academicInfoByYear(offeringId, year),
    queryFn: async () => {
      const response = await api.get<OfferingAcademicInfo>(
        API_ENDPOINTS.ORGANIZATION.GET_ACADEMIC_INFO_BY_YEAR(offeringId, year)
      );
      return response.data;
    },
    enabled: !!offeringId && !!year,
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
// MUTATIONS (CREATE, UPDATE, DELETE) - TIER 1: MAJOR PROGRAM
// =====================================================================

/**
 * Create a new major program
 */
export function useCreateMajorProgram() {
  const queryClient = useQueryClient();

  return useMutation<
    MajorProgram,
    AxiosError<ApiErrorResponse>,
    MajorProgramCreate
  >({
    mutationFn: async (data) => {
      const response = await api.post<MajorProgram>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_MAJOR_PROGRAM,
        data
      );
      return response.data;
    },
    onSuccess: (newProgram) => {
      toast.success("Chương trình đào tạo mới đã được tạo!", {
        description: newProgram.name,
      });
      // Invalidate relevant queries
      queryClient.invalidateQueries({ queryKey: organizationKeys.majorPrograms() });
      queryClient.invalidateQueries({ queryKey: organizationKeys.list() });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Tạo chương trình thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing major program
 */
export function useUpdateMajorProgram() {
  const queryClient = useQueryClient();

  return useMutation<
    MajorProgram,
    AxiosError<ApiErrorResponse>,
    { id: number; data: MajorProgramUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put<MajorProgram>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_MAJOR_PROGRAM(id),
        data
      );
      return response.data;
    },
    onSuccess: (updatedProgram) => {
      toast.success("Chương trình đã được cập nhật!", {
        description: updatedProgram.name,
      });
      queryClient.invalidateQueries({ queryKey: organizationKeys.majorPrograms() });
      queryClient.invalidateQueries({ queryKey: organizationKeys.list() });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Cập nhật chương trình thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Delete a major program
 */
export function useDeleteMajorProgram() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_MAJOR_PROGRAM(id));
    },
    onSuccess: () => {
      toast.success("Chương trình đào tạo đã được xóa!");
      queryClient.invalidateQueries({ queryKey: organizationKeys.majorPrograms() });
      queryClient.invalidateQueries({ queryKey: organizationKeys.list() });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Xóa chương trình thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - TIER 2: PROGRAM OFFERING
// =====================================================================

/**
 * Create a new program offering
 */
export function useCreateProgramOffering() {
  const queryClient = useQueryClient();

  return useMutation<
    ProgramOffering,
    AxiosError<ApiErrorResponse>,
    ProgramOfferingCreate & { programId: number }
  >({
    mutationFn: async ({ programId, ...data }) => {
      const response = await api.post<ProgramOffering>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_OFFERING(programId),
        { ...data, program_id: programId } // Include program_id in body for backend validation
      );
      return response.data;
    },
    onSuccess: (newOffering, variables) => {
      toast.success("Loại hình đào tạo mới đã được tạo!", {
        description: newOffering.offering_type,
      });
      // Invalidate offerings list and major program detail
      queryClient.invalidateQueries({
        queryKey: organizationKeys.offeringsList(variables.programId)
      });
      queryClient.invalidateQueries({
        queryKey: organizationKeys.majorProgramDetail(variables.programId)
      });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Tạo loại hình thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update an existing program offering
 */
export function useUpdateProgramOffering() {
  const queryClient = useQueryClient();

  return useMutation<
    ProgramOffering,
    AxiosError<ApiErrorResponse>,
    { id: number; data: ProgramOfferingUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.put<ProgramOffering>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_OFFERING(id),
        data
      );
      return response.data;
    },
    onSuccess: (updatedOffering) => {
      toast.success("Loại hình đào tạo đã được cập nhật!", {
        description: updatedOffering.offering_type,
      });
      queryClient.invalidateQueries({ queryKey: organizationKeys.offerings() });
      queryClient.invalidateQueries({ queryKey: organizationKeys.majorPrograms() });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Cập nhật loại hình thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Delete a program offering
 */
export function useDeleteProgramOffering() {
  const queryClient = useQueryClient();

  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_OFFERING(id));
    },
    onSuccess: () => {
      toast.success("Loại hình đào tạo đã được xóa!");
      queryClient.invalidateQueries({ queryKey: organizationKeys.offerings() });
      queryClient.invalidateQueries({ queryKey: organizationKeys.majorPrograms() });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Xóa loại hình thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// MUTATIONS (CREATE, UPDATE, DELETE) - TIER 3: OFFERING ACADEMIC INFO
// =====================================================================

/**
 * Create new academic info for an offering
 */
export function useCreateOfferingAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation<
    OfferingAcademicInfo,
    AxiosError<ApiErrorResponse>,
    OfferingAcademicInfoCreate & { offeringId: number }
  >({
    mutationFn: async ({ offeringId, ...data }) => {
      const response = await api.post<OfferingAcademicInfo>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.CREATE_ACADEMIC_INFO(offeringId),
        data
      );
      return response.data;
    },
    onSuccess: (newInfo, variables) => {
      toast.success("Thông tin tuyển sinh đã được tạo!", {
        description: `Năm học ${newInfo.academic_year}`,
      });
      // Invalidate academic info list
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoList(variables.offeringId),
      });
      queryClient.invalidateQueries({
        queryKey: organizationKeys.offeringDetail(variables.offeringId),
      });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Tạo thông tin tuyển sinh thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Update existing academic info
 */
export function useUpdateOfferingAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation<
    OfferingAcademicInfo,
    AxiosError<ApiErrorResponse>,
    { id: number; data: OfferingAcademicInfoUpdate }
  >({
    mutationFn: async ({ id, data }) => {
      const response = await api.patch<OfferingAcademicInfo>(
        API_ENDPOINTS.ADMIN.ORGANIZATION.UPDATE_ACADEMIC_INFO(id),
        data
      );
      return response.data;
    },
    onSuccess: (updatedInfo) => {
      toast.success("Thông tin tuyển sinh đã được cập nhật!", {
        description: `Năm học ${updatedInfo.academic_year}`,
      });
      // Invalidate queries
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoList(updatedInfo.offering_id),
      });
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoByYear(updatedInfo.offering_id, updatedInfo.academic_year),
      });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Cập nhật thông tin tuyển sinh thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

/**
 * Delete academic info
 */
export function useDeleteOfferingAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation<
    void,
    AxiosError<ApiErrorResponse>,
    { id: number; offeringId: number }
  >({
    mutationFn: async ({ id }) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_ACADEMIC_INFO(id));
    },
    onSuccess: (_, variables) => {
      toast.success("Thông tin tuyển sinh đã được xóa!");
      // Invalidate academic info list
      queryClient.invalidateQueries({
        queryKey: organizationKeys.academicInfoList(variables.offeringId),
      });
    },
    onError: (error) => {
      const detail = error.response?.data?.detail;
      const message = typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(e => e.msg).join(', ')
          : "Xóa thông tin tuyển sinh thất bại";
      toast.error("Lỗi", { description: message });
    },
  });
}

// =====================================================================
// LEGACY HOOKS (DEPRECATED - For backward compatibility)
// =====================================================================

/**
 * @deprecated Use useMajorPrograms instead
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
 * @deprecated Use useMajorProgram instead
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
 * @deprecated Use useCreateMajorProgram instead
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
 * @deprecated Use useUpdateMajorProgram instead
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
 * @deprecated Use useDeleteMajorProgram instead
 * Delete a major
 */
export function useDeleteMajor() {
  return useMutation<void, AxiosError<ApiErrorResponse>, number>({
    mutationFn: async (id) => {
      await api.delete(API_ENDPOINTS.ADMIN.ORGANIZATION.DELETE_MAJOR(id));
    },
    onSuccess: () => {
      toast.success("Ngành học đã được xóa!");
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

/**
 * @deprecated Use useOfferingAcademicInfoList instead
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
 * @deprecated Use useOfferingAcademicInfoByYear instead
 * Get academic info for a specific year
 */
export function useAcademicInfoByYear(majorId: number, year: number) {
  return useQuery<MajorAcademicInfo, AxiosError<ApiErrorResponse>>({
    queryKey: organizationKeys.academicInfoByYearLegacy(majorId, year),
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

/**
 * @deprecated Use useCreateOfferingAcademicInfo instead
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
 * @deprecated Use useUpdateOfferingAcademicInfo instead
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
        queryKey: organizationKeys.academicInfoByYearLegacy(updatedInfo.major_id, updatedInfo.academic_year),
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
 * @deprecated Use useDeleteOfferingAcademicInfo instead
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
export function getAllDescendantIds(unit: OrganizationUnit): Set<number> {
  const descendants = new Set<number>([unit.id]);

  const collectDescendants = (currentUnit: OrganizationUnit) => {
    if (currentUnit.children && currentUnit.children.length > 0) {
      currentUnit.children.forEach(child => {
        descendants.add(child.id);
        collectDescendants(child); // Recursive
      });
    }
  };

  collectDescendants(unit);
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
  // Helper function to find a unit in tree structure
  const findUnitInTree = (units: OrganizationUnit[], id: number): OrganizationUnit | null => {
    for (const unit of units) {
      if (unit.id === id) return unit;
      if (unit.children && unit.children.length > 0) {
        const found = findUnitInTree(unit.children, id);
        if (found) return found;
      }
    }
    return null;
  };

  const childUnit = findUnitInTree(allUnits, childId);
  if (!childUnit) return false;

  const descendants = getAllDescendantIds(childUnit);
  return descendants.has(parentId);
}

// =====================================================================
// CONFIGURATION HOOKS
// =====================================================================

/**
 * Fetch degree level configurations
 */
export function useDegreeLevels(activeOnly: boolean = true) {
  return useQuery<ConfigDegreeLevel[], AxiosError<ApiErrorResponse>>({
    queryKey: ['config', 'degree-levels', activeOnly],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (activeOnly) params.append("active_only", "true");

      const response = await api.get<ConfigDegreeLevel[]>(
        `${API_ENDPOINTS.ADMIN.CONFIG.LIST_DEGREE_LEVELS}${
          params.toString() ? `?${params.toString()}` : ""
        }`
      );
      return response.data;
    },
    staleTime: 1000 * 60 * 30, // Cache for 30 minutes (config changes infrequently)
  });
}

/**
 * Fetch offering type configurations
 */
export function useOfferingTypes(activeOnly: boolean = true) {
  return useQuery<ConfigOfferingType[], AxiosError<ApiErrorResponse>>({
    queryKey: ['config', 'offering-types', activeOnly],
    queryFn: async () => {
      const params = new URLSearchParams();
      if (activeOnly) params.append("active_only", "true");

      const response = await api.get<ConfigOfferingType[]>(
        `${API_ENDPOINTS.ADMIN.CONFIG.LIST_OFFERING_TYPES}${
          params.toString() ? `?${params.toString()}` : ""
        }`
      );
      return response.data;
    },
    staleTime: 1000 * 60 * 30, // Cache for 30 minutes (config changes infrequently)
  });
}
