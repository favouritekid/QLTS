/**
 * React Query hooks for admin commune KV CRUD (PR-A).
 *
 * Query key includes the full filter/pagination params so each
 * page/province/search combo caches independently. Mutations invalidate the
 * whole `commune-kv` tree (any write can shift pagination/totals).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  createCommune,
  importCommuneCsv,
  listCommunes,
  replaceCommuneArea,
  retireCommune,
  updateCommune,
  type ListCommunesParams,
} from "@/lib/api/admin-commune-kv"
import type {
  CommuneAreaCreate,
  CommuneAreaUpdate,
  CommuneReplaceArea,
} from "@/lib/zod/commune-kv"

export const communeKvKeys = {
  all: ["commune-kv"] as const,
  list: (params: ListCommunesParams) =>
    [...communeKvKeys.all, "list", params] as const,
}

export function useCommunes(params: ListCommunesParams) {
  return useQuery({
    queryKey: communeKvKeys.list(params),
    queryFn: () => listCommunes(params),
    staleTime: 30 * 1000,
  })
}

export function useCreateCommune() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: CommuneAreaCreate) => createCommune(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: communeKvKeys.all }),
  })
}

export function useUpdateCommune() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: CommuneAreaUpdate }) =>
      updateCommune(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: communeKvKeys.all }),
  })
}

export function useReplaceCommuneArea() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: CommuneReplaceArea }) =>
      replaceCommuneArea(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: communeKvKeys.all }),
  })
}

export function useRetireCommune() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => retireCommune(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: communeKvKeys.all }),
  })
}

export function useImportCommuneCsv() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => importCommuneCsv(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: communeKvKeys.all }),
  })
}
