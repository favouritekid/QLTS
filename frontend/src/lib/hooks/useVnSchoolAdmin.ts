/**
 * React Query hooks for admin vn_school + KV assignment CRUD (PR-B).
 *
 * School list keyed theo filter/pagination. KV assignment keyed theo schoolId.
 * Mutations invalidate đúng nhánh (school write → school tree; KV write → KV
 * của school đó + school tree để current_kv refresh).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import {
  addKvAssignment,
  createSchool,
  deactivateSchool,
  deleteKvAssignment,
  importSchoolCsv,
  listKvAssignments,
  listSchoolProvinces,
  listSchools,
  updateKvAssignment,
  updateSchool,
  type ListSchoolsParams,
} from "@/lib/api/admin-vn-school"
import type {
  KvAssignmentCreate,
  KvAssignmentUpdate,
  SchoolCreate,
  SchoolUpdate,
} from "@/lib/zod/vn-school-admin"

export const vnSchoolKeys = {
  all: ["vn-school-admin"] as const,
  list: (params: ListSchoolsParams) =>
    [...vnSchoolKeys.all, "list", params] as const,
  provinces: () => [...vnSchoolKeys.all, "provinces"] as const,
  kv: (schoolId: number) => [...vnSchoolKeys.all, "kv", schoolId] as const,
}

export function useSchools(params: ListSchoolsParams) {
  return useQuery({
    queryKey: vnSchoolKeys.list(params),
    queryFn: () => listSchools(params),
    staleTime: 30 * 1000,
  })
}

export function useSchoolProvinces() {
  return useQuery({
    queryKey: vnSchoolKeys.provinces(),
    queryFn: () => listSchoolProvinces(),
    staleTime: 60 * 60 * 1000,
  })
}

export function useCreateSchool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (data: SchoolCreate) => createSchool(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: vnSchoolKeys.all }),
  })
}

export function useUpdateSchool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: SchoolUpdate }) =>
      updateSchool(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: vnSchoolKeys.all }),
  })
}

export function useDeactivateSchool() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deactivateSchool(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: vnSchoolKeys.all }),
  })
}

export function useImportSchoolCsv() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => importSchoolCsv(file),
    onSuccess: () => qc.invalidateQueries({ queryKey: vnSchoolKeys.all }),
  })
}

// --- KV assignment ---

export function useKvAssignments(schoolId: number | null) {
  return useQuery({
    queryKey: vnSchoolKeys.kv(schoolId ?? 0),
    queryFn: () => listKvAssignments(schoolId!),
    enabled: schoolId != null,
    staleTime: 30 * 1000,
  })
}

export function useAddKvAssignment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ schoolId, data }: { schoolId: number; data: KvAssignmentCreate }) =>
      addKvAssignment(schoolId, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: vnSchoolKeys.all }),
  })
}

export function useUpdateKvAssignment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, data }: { id: number; data: KvAssignmentUpdate }) =>
      updateKvAssignment(id, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: vnSchoolKeys.all }),
  })
}

export function useDeleteKvAssignment() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => deleteKvAssignment(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: vnSchoolKeys.all }),
  })
}
