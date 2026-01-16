/**
 * useProgramData Hook
 *
 * React Query hooks for Phase 2 program data management
 * Provides CRUD operations for program entities
 */

"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import * as programDataApi from "@/lib/api/program-data";
import type {
  BaseEntityUpdate,
  OfferingAcademicInfoUpdate
} from "@/app/(dashboard)/admin/admission-config/_components/shared/types";

// Error type for API errors
interface ApiError {
  response?: {
    data?: {
      detail?: string;
    };
  };
}

// ============================================
// MAJOR PROGRAMS
// ============================================

export function useMajorPrograms() {
  return useQuery({
    queryKey: ["major-programs"],
    queryFn: programDataApi.getMajorPrograms,
  });
}

export function useCreateMajorProgram() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: programDataApi.createMajorProgram,
    onSuccess: () => {
      toast.success("Major program created successfully");
      queryClient.invalidateQueries({ queryKey: ["major-programs"] });
      queryClient.invalidateQueries({ queryKey: ["phase2-check"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create major program");
    },
  });
}

export function useUpdateMajorProgram() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof programDataApi.updateMajorProgram>[1] }) =>
      programDataApi.updateMajorProgram(id, data),
    onSuccess: () => {
      toast.success("Major program updated successfully");
      queryClient.invalidateQueries({ queryKey: ["major-programs"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update major program");
    },
  });
}

export function useDeleteMajorProgram() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: programDataApi.deleteMajorProgram,
    onSuccess: () => {
      toast.success("Major program deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["major-programs"] });
      queryClient.invalidateQueries({ queryKey: ["program-offerings"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete major program");
    },
  });
}

// ============================================
// PROGRAM OFFERINGS
// ============================================

export function useProgramOfferings() {
  return useQuery({
    queryKey: ["program-offerings"],
    queryFn: programDataApi.getProgramOfferings,
  });
}

export function useProgramOfferingsByMajor(majorId: number | undefined) {
  return useQuery({
    queryKey: ["program-offerings", "by-major", majorId],
    queryFn: () => programDataApi.getProgramOfferingsByMajor(majorId!),
    enabled: !!majorId,
  });
}

export function useCreateProgramOffering() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: programDataApi.createProgramOffering,
    onSuccess: () => {
      toast.success("Program offering created successfully");
      queryClient.invalidateQueries({ queryKey: ["program-offerings"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create program offering");
    },
  });
}

export function useUpdateProgramOffering() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: Parameters<typeof programDataApi.updateProgramOffering>[1] }) =>
      programDataApi.updateProgramOffering(id, data),
    onSuccess: () => {
      toast.success("Program offering updated successfully");
      queryClient.invalidateQueries({ queryKey: ["program-offerings"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update program offering");
    },
  });
}

export function useDeleteProgramOffering() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: programDataApi.deleteProgramOffering,
    onSuccess: () => {
      toast.success("Program offering deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["program-offerings"] });
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete program offering");
    },
  });
}

// ============================================
// OFFERING ACADEMIC INFO
// ============================================

export function useOfferingAcademicInfos() {
  return useQuery({
    queryKey: ["academic-infos"],
    queryFn: programDataApi.getOfferingAcademicInfos,
  });
}

export function useAcademicInfoByOffering(offeringId: number | undefined) {
  return useQuery({
    queryKey: ["academic-infos", "by-offering", offeringId],
    queryFn: () => programDataApi.getAcademicInfoByOffering(offeringId!),
    enabled: !!offeringId,
  });
}

export function useCreateOfferingAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: programDataApi.createOfferingAcademicInfo,
    onSuccess: () => {
      toast.success("Academic info created successfully");
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to create academic info");
    },
  });
}

export function useUpdateOfferingAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: OfferingAcademicInfoUpdate }) =>
      programDataApi.updateOfferingAcademicInfo(id, data),
    onSuccess: () => {
      toast.success("Academic info updated successfully");
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to update academic info");
    },
  });
}

export function useDeleteOfferingAcademicInfo() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: programDataApi.deleteOfferingAcademicInfo,
    onSuccess: () => {
      toast.success("Academic info deleted successfully");
      queryClient.invalidateQueries({ queryKey: ["academic-infos"] });
    },
    onError: (error: ApiError) => {
      toast.error(error.response?.data?.detail || "Failed to delete academic info");
    },
  });
}
