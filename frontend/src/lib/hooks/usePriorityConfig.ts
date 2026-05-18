/**
 * React Query hooks for priority_area_config + priority_object_config
 * admin CRUD (Q9 #07 PR3 admin FE).
 *
 * One query key family per year scope so an edit in 2026 doesn't
 * flush 2025/2027 caches. Mutations invalidate the relevant year +
 * the root key for the cross-cutting clone/seed buttons.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  cloneFromYear,
  createArea,
  createObject,
  listAreas,
  listObjects,
  retireArea,
  retireObject,
  seedTt052021Defaults,
  updateArea,
  updateObject,
} from "@/lib/api/priority-config"
import type {
  PriorityAreaConfigCreate,
  PriorityAreaConfigUpdate,
  PriorityConfigCloneRequest,
  PriorityConfigSeedDefaultsRequest,
  PriorityObjectConfigCreate,
  PriorityObjectConfigUpdate,
} from "@/lib/zod/priority-config"

// ============================================
// QUERY KEYS
// ============================================

export const priorityConfigKeys = {
  all: ["priority-config"] as const,
  areas: () => [...priorityConfigKeys.all, "areas"] as const,
  areasByYear: (year: number, activeOnly: boolean) =>
    [...priorityConfigKeys.areas(), year, activeOnly] as const,
  objects: () => [...priorityConfigKeys.all, "objects"] as const,
  objectsByYear: (year: number, activeOnly: boolean) =>
    [...priorityConfigKeys.objects(), year, activeOnly] as const,
}

// ============================================
// READ HOOKS
// ============================================

export function usePriorityAreas(
  academicYear: number | undefined,
  activeOnly: boolean = true,
) {
  return useQuery({
    queryKey: priorityConfigKeys.areasByYear(academicYear ?? 0, activeOnly),
    queryFn: () => listAreas(academicYear!, activeOnly),
    enabled: !!academicYear,
    staleTime: 30 * 1000,
  })
}

export function usePriorityObjects(
  academicYear: number | undefined,
  activeOnly: boolean = true,
) {
  return useQuery({
    queryKey: priorityConfigKeys.objectsByYear(academicYear ?? 0, activeOnly),
    queryFn: () => listObjects(academicYear!, activeOnly),
    enabled: !!academicYear,
    staleTime: 30 * 1000,
  })
}

// ============================================
// AREA MUTATIONS
// ============================================

export function useCreatePriorityArea(academicYear: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: PriorityAreaConfigCreate) => createArea(academicYear, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.areas() })
    },
  })
}

export function useUpdatePriorityArea() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      areaId,
      data,
    }: {
      areaId: number
      data: PriorityAreaConfigUpdate
    }) => updateArea(areaId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.areas() })
    },
  })
}

export function useRetirePriorityArea() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (areaId: number) => retireArea(areaId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.areas() })
    },
  })
}

// ============================================
// OBJECT MUTATIONS
// ============================================

export function useCreatePriorityObject(academicYear: number) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (data: PriorityObjectConfigCreate) =>
      createObject(academicYear, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.objects() })
    },
  })
}

export function useUpdatePriorityObject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      objectId,
      data,
    }: {
      objectId: number
      data: PriorityObjectConfigUpdate
    }) => updateObject(objectId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.objects() })
    },
  })
}

export function useRetirePriorityObject() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (objectId: number) => retireObject(objectId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.objects() })
    },
  })
}

// ============================================
// CLONE + SEED
// ============================================

export function useClonePriorityConfig() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: PriorityConfigCloneRequest) => cloneFromYear(payload),
    onSuccess: () => {
      // Clone hits a year that's not the currently-selected one, so
      // invalidate the whole tree (areas + objects across years).
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.all })
    },
  })
}

export function useSeedPriorityDefaults() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: PriorityConfigSeedDefaultsRequest) =>
      seedTt052021Defaults(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: priorityConfigKeys.all })
    },
  })
}
