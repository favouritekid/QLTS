/**
 * usePathSubjectGroupConfigs Hook (#7 — admin "Tổ hợp môn" tab)
 *
 * React Query hooks for admin CRUD of path_subject_group_config + items.
 * Mirrors useAdmissionPaths mutation/invalidation patterns.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import type { QueryClient } from "@tanstack/react-query"

import {
  getPathSubjectGroupConfigsAdmin,
  createPathSubjectGroupConfig,
  updatePathSubjectGroupConfig,
  deletePathSubjectGroupConfig,
  addPathSubjectGroupItem,
  updatePathSubjectGroupItem,
  deletePathSubjectGroupItem,
} from "@/lib/api/admission-paths"
import type {
  PathSubjectGroupConfigCreatePayload,
  PathSubjectGroupConfigUpdatePayload,
  PathSubjectGroupItemPayload,
  PathSubjectGroupItemUpdatePayload,
} from "@/lib/api/admission-paths"
import { admissionPathKeys } from "./useAdmissionPaths"

// ============================================
// QUERY KEYS
// ============================================

export const pathSgConfigKeys = {
  all: ["path-sg-configs-admin"] as const,
  list: (pathId: number) => ["path-sg-configs-admin", pathId] as const,
}

/**
 * Invalidate every cache a config/item mutation can affect.
 *
 * NB: ``["path-sg-configs", pathId]`` (the AddChoiceDialog officer GET) is a
 * raw literal NOT under ``admissionPathKeys.all``, so it must be invalidated
 * explicitly — otherwise the multi-NV "Thêm nguyện vọng" dropdown stays stale
 * after the admin adds/edits a combination. Same for ``["quota-matrix"]``.
 */
function invalidatePathSgConfigs(qc: QueryClient, pathId: number) {
  // Return the combined promise so the mutation's onSuccess AWAITS the refetch
  // — mutateAsync (and isPending) stay active until the list is fresh, closing
  // the window where the UI unlocks on a stale config → re-action 409/404.
  return Promise.all([
    qc.invalidateQueries({ queryKey: pathSgConfigKeys.list(pathId) }),
    qc.invalidateQueries({ queryKey: ["path-sg-configs", pathId] }),
    qc.invalidateQueries({ queryKey: admissionPathKeys.detail(pathId) }),
    qc.invalidateQueries({ queryKey: admissionPathKeys.all }),
    qc.invalidateQueries({ queryKey: ["quota-matrix"] }),
  ])
}

// ============================================
// READ
// ============================================

export function usePathSubjectGroupConfigsAdmin(
  pathId: number | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: pathSgConfigKeys.list(pathId ?? 0),
    queryFn: () => getPathSubjectGroupConfigsAdmin(pathId as number),
    enabled: enabled && pathId != null,
  })
}

// ============================================
// MUTATIONS (config CRUD + item CRUD)
// ============================================

export function useCreatePathSubjectGroupConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      pathId: number
      data: PathSubjectGroupConfigCreatePayload
    }) => createPathSubjectGroupConfig(vars.pathId, vars.data),
    onSuccess: (_r, vars) => invalidatePathSgConfigs(qc, vars.pathId),
  })
}

export function useUpdatePathSubjectGroupConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      pathId: number
      configId: number
      data: PathSubjectGroupConfigUpdatePayload
    }) => updatePathSubjectGroupConfig(vars.configId, vars.data),
    onSuccess: (_r, vars) => invalidatePathSgConfigs(qc, vars.pathId),
  })
}

export function useDeletePathSubjectGroupConfig() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: { pathId: number; configId: number }) =>
      deletePathSubjectGroupConfig(vars.configId),
    onSuccess: (_r, vars) => invalidatePathSgConfigs(qc, vars.pathId),
  })
}

export function useAddPathSubjectGroupItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      pathId: number
      configId: number
      data: PathSubjectGroupItemPayload
    }) => addPathSubjectGroupItem(vars.configId, vars.data),
    onSuccess: (_r, vars) => invalidatePathSgConfigs(qc, vars.pathId),
  })
}

export function useUpdatePathSubjectGroupItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      pathId: number
      configId: number
      itemId: number
      data: PathSubjectGroupItemUpdatePayload
    }) => updatePathSubjectGroupItem(vars.configId, vars.itemId, vars.data),
    onSuccess: (_r, vars) => invalidatePathSgConfigs(qc, vars.pathId),
  })
}

export function useDeletePathSubjectGroupItem() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (vars: { pathId: number; configId: number; itemId: number }) =>
      deletePathSubjectGroupItem(vars.configId, vars.itemId),
    onSuccess: (_r, vars) => invalidatePathSgConfigs(qc, vars.pathId),
  })
}
