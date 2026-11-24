/**
 * React Query hooks — công cụ ghép tên trường THCS gõ tay (owner 22-11).
 *
 * Ghép / huỷ ghép / tạo trường ⇒ invalidate danh sách nhóm (+ danh mục trường khi
 * tạo trường mới). Áp ghép (kể cả chạy thử) là mutation: không cache kết quả.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  applyThcsMapping,
  createSchoolFromThcsGroup,
  listThcsGroups,
  mapThcsGroup,
  unmapThcsGroup,
  type ListThcsGroupsParams,
} from "@/lib/api/thcs-school-mapping"
import { vnSchoolKeys } from "@/lib/hooks/useVnSchoolAdmin"
import type {
  ThcsCreateSchoolFromGroup,
  ThcsMappingApplyRequest,
  ThcsMapRequest,
} from "@/lib/zod/thcs-school-mapping"

export const thcsMappingKeys = {
  all: ["thcs-school-mapping"] as const,
  groups: (params: ListThcsGroupsParams) =>
    [...thcsMappingKeys.all, "groups", params] as const,
}

export function useThcsGroups(params: ListThcsGroupsParams) {
  return useQuery({
    queryKey: thcsMappingKeys.groups(params),
    queryFn: () => listThcsGroups(params),
    staleTime: 30 * 1000,
  })
}

export function useMapThcsGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ThcsMapRequest) => mapThcsGroup(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: thcsMappingKeys.all }),
  })
}

export function useUnmapThcsGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (normalizedName: string) => unmapThcsGroup(normalizedName),
    onSuccess: () => qc.invalidateQueries({ queryKey: thcsMappingKeys.all }),
  })
}

export function useCreateSchoolFromThcsGroup() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ThcsCreateSchoolFromGroup) =>
      createSchoolFromThcsGroup(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: thcsMappingKeys.all })
      qc.invalidateQueries({ queryKey: vnSchoolKeys.all })
    },
  })
}

export function useApplyThcsMapping() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: ThcsMappingApplyRequest) => applyThcsMapping(data),
    onSuccess: (result) => {
      if (result.applied)
        qc.invalidateQueries({ queryKey: thcsMappingKeys.all })
    },
  })
}
