/**
 * React Query hooks for system_config admin CRUD.
 */
"use client"

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import type { AxiosError } from "axios"
import { toast } from "sonner"

import {
  listSystemConfig,
  updateSystemConfig,
} from "@/lib/api/system-config"
import type {
  SystemConfigListResponse,
  SystemConfigResponse,
  SystemConfigUpdate,
} from "@/lib/zod/system-config"
// Import ApiErrorResponse from error-handler so the mutation generic
// matches the handleApiError parameter type. Two ApiErrorResponse defs
// exist in this repo (types/api.types vs lib/error-handler) — pairing
// with handleApiError requires the error-handler one.
import { handleApiError, type ApiErrorResponse } from "@/lib/error-handler"

const QK = {
  list: () => ["system-config", "list"] as const,
  detail: (key: string) => ["system-config", "detail", key] as const,
}

export function useSystemConfigList() {
  return useQuery<SystemConfigListResponse>({
    queryKey: QK.list(),
    queryFn: listSystemConfig,
  })
}

export function useUpdateSystemConfig() {
  const qc = useQueryClient()
  return useMutation<
    SystemConfigResponse,
    AxiosError<ApiErrorResponse>,
    { key: string; data: SystemConfigUpdate }
  >({
    mutationFn: ({ key, data }) => updateSystemConfig(key, data),
    onSuccess: (updated) => {
      // Surgical cache update keeps the list in sync without a network
      // roundtrip; falling back to invalidate would also work but reflows
      // the table.
      qc.setQueryData<SystemConfigListResponse>(QK.list(), (prev) => {
        if (!prev) return prev
        return {
          ...prev,
          items: prev.items.map((row) =>
            row.key === updated.key ? updated : row
          ),
        }
      })
      qc.setQueryData(QK.detail(updated.key), updated)
      toast.success(`Đã cập nhật "${updated.key}"`)
    },
    onError: (err) => {
      handleApiError(err, { context: "cập nhật cấu hình hệ thống" })
    },
  })
}
