/**
 * useMasterData Hook
 *
 * React Query hooks for Phase 1 master data management
 * Provides CRUD operations for all master data entities
 */

"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as masterDataApi from "@/lib/api/master-data";
import type { BaseEntityUpdate } from "@/app/(dashboard)/admin/admission-config/_components/shared/types";

// Error type for API errors
interface ApiError {
  response?: {
    data?: {
      detail?: string;
    };
  };
}

// ============================================
// ORGANIZATION UNITS
// ============================================

export function useOrganizationUnits() {
  return useQuery({
    queryKey: ["organization-units"],
    queryFn: masterDataApi.getOrganizationUnits,
  });
}

export function useCreateOrganizationUnit() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.createOrganizationUnit,
    onSuccess: () => {
      toast.success("Organization unit created successfully");
      queryClient.invalidateQueries({ queryKey: ["organization-units"] });
      queryClient.invalidateQueries({ queryKey: ["major-programs"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create organization unit");
    },
  });
}

export function useUpdateOrganizationUnit() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BaseEntityUpdate }) =>
      masterDataApi.updateOrganizationUnit(id, data),
    onSuccess: () => {
      toast.success("Organization unit updated successfully");
      queryClient.invalidateQueries({ queryKey: ["organization-units"] });
      queryClient.invalidateQueries({ queryKey: ["major-programs"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update organization unit");
    },
  });
}

export function useDeleteOrganizationUnit() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.deleteOrganizationUnit,
    onSuccess: () => {
      toast.success("Organization unit deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["organization-units"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete organization unit");
    },
  });
}

// ============================================
// OFFERING TYPES
// ============================================

export function useOfferingTypes() {
  return useQuery({
    queryKey: ["offering-types"],
    queryFn: masterDataApi.getOfferingTypes,
  });
}

export function useCreateOfferingType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.createOfferingType,
    onSuccess: () => {
      toast.success("Offering type created successfully");
      queryClient.invalidateQueries({ queryKey: ["offering-types"] });
      queryClient.invalidateQueries({ queryKey: ["phase1-check"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create offering type");
    },
  });
}

export function useUpdateOfferingType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BaseEntityUpdate }) =>
      masterDataApi.updateOfferingType(id, data),
    onSuccess: () => {
      toast.success("Offering type updated successfully");
      queryClient.invalidateQueries({ queryKey: ["offering-types"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update offering type");
    },
  });
}

export function useDeleteOfferingType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.deleteOfferingType,
    onSuccess: () => {
      toast.success("Offering type deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["offering-types"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete offering type");
    },
  });
}

// ============================================
// ADMISSION METHODS
// ============================================

export function useAdmissionMethods() {
  return useQuery({
    queryKey: ["admission-methods"],
    queryFn: masterDataApi.getAdmissionMethods,
  });
}

export function useCreateAdmissionMethod() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.createAdmissionMethod,
    onSuccess: () => {
      toast.success("Admission method created successfully");
      queryClient.invalidateQueries({ queryKey: ["admission-methods"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create admission method");
    },
  });
}

export function useUpdateAdmissionMethod() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BaseEntityUpdate }) =>
      masterDataApi.updateAdmissionMethod(id, data),
    onSuccess: () => {
      toast.success("Admission method updated successfully");
      queryClient.invalidateQueries({ queryKey: ["admission-methods"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update admission method");
    },
  });
}

export function useDeleteAdmissionMethod() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.deleteAdmissionMethod,
    onSuccess: () => {
      toast.success("Admission method deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["admission-methods"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete admission method");
    },
  });
}

// ============================================
// DOCUMENT TYPES
// ============================================

export function useDocumentTypes() {
  return useQuery({
    queryKey: ["document-types"],
    queryFn: masterDataApi.getDocumentTypes,
  });
}

export function useCreateDocumentType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.createDocumentType,
    onSuccess: () => {
      toast.success("Document type created successfully");
      queryClient.invalidateQueries({ queryKey: ["document-types"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create document type");
    },
  });
}

export function useUpdateDocumentType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BaseEntityUpdate }) =>
      masterDataApi.updateDocumentType(id, data),
    onSuccess: () => {
      toast.success("Document type updated successfully");
      queryClient.invalidateQueries({ queryKey: ["document-types"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update document type");
    },
  });
}

export function useDeleteDocumentType() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.deleteDocumentType,
    onSuccess: () => {
      toast.success("Document type deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["document-types"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete document type");
    },
  });
}

// ============================================
// SUBJECTS
// ============================================

export function useSubjects() {
  return useQuery({
    queryKey: ["subjects"],
    queryFn: masterDataApi.getSubjects,
  });
}

export function useCreateSubject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.createSubject,
    onSuccess: () => {
      toast.success("Subject created successfully");
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create subject");
    },
  });
}

export function useUpdateSubject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BaseEntityUpdate }) =>
      masterDataApi.updateSubject(id, data),
    onSuccess: () => {
      toast.success("Subject updated successfully");
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update subject");
    },
  });
}

export function useDeleteSubject() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.deleteSubject,
    onSuccess: () => {
      toast.success("Subject deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["subjects"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete subject");
    },
  });
}

// ============================================
// SUBJECT GROUPS
// ============================================

export function useSubjectGroups() {
  return useQuery({
    queryKey: ["subject-groups"],
    queryFn: masterDataApi.getSubjectGroups,
  });
}

export function useCreateSubjectGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.createSubjectGroup,
    onSuccess: () => {
      toast.success("Subject group created successfully");
      queryClient.invalidateQueries({ queryKey: ["subject-groups"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create subject group");
    },
  });
}

export function useUpdateSubjectGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: BaseEntityUpdate }) =>
      masterDataApi.updateSubjectGroup(id, data),
    onSuccess: () => {
      toast.success("Subject group updated successfully");
      queryClient.invalidateQueries({ queryKey: ["subject-groups"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update subject group");
    },
  });
}

export function useDeleteSubjectGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: masterDataApi.deleteSubjectGroup,
    onSuccess: () => {
      toast.success("Subject group deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["subject-groups"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete subject group");
    },
  });
}

// ============================================
// SUBJECT GROUP M2M
// ============================================

export function useAddSubjectToGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, subjectId, position }: { groupId: number; subjectId: number; position: number }) =>
      masterDataApi.addSubjectToGroup(groupId, subjectId, position),
    onSuccess: () => {
      toast.success("Subject added to group");
      queryClient.invalidateQueries({ queryKey: ["subject-groups"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to add subject to group");
    },
  });
}

export function useRemoveSubjectFromGroup() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ groupId, subjectId }: { groupId: number; subjectId: number }) =>
      masterDataApi.removeSubjectFromGroup(groupId, subjectId),
    onSuccess: () => {
      toast.success("Subject removed from group");
      queryClient.invalidateQueries({ queryKey: ["subject-groups"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to remove subject from group");
    },
  });
}
