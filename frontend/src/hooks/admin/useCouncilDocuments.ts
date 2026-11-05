/**
 * Văn bản Hội đồng tuyển sinh (Lần xét tuyển GĐ1) — React Query hooks + view
 * model cờ quyền.
 *
 * Ẩn / hiện theo CỜ của máy chủ (`GET /quyen`), KHÔNG theo `user.role`
 * (FRONTEND_ARCHITECTURE_V3 §2.2). 403 ở route cờ (vai không có dòng Casbin)
 * ⇒ "không có quyền": mọi cờ tắt. Lỗi khác ⇒ trạng thái lỗi, cũng mọi cờ tắt
 * (fail-closed) — máy chủ vẫn là chốt chặn thật.
 *
 * ⚠️ DỮ LIỆU CÁ NHÂN (danh sách mã hồ sơ = CCCD):
 *   - query xem mã: `gcTime: 0`, `staleTime: 0`, không retry, không refetch
 *     khi focus ⇒ React Query gỡ khỏi cache ngay khi component dùng nó unmount
 *     (bấm "Ẩn" / rời trang);
 *   - mutation dựng bộ: `gcTime: 0` — biến số (thân yêu cầu có danh sách mã)
 *     không nằm lại trong MutationCache sau khi xong;
 *   - không persist (QueryClient của app không có persister — test khoá), không
 *     Zustand, không storage, không `console.*`, không URL.
 */
import { useMemo } from "react"
import axios from "axios"
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"

import {
  createCouncilSet,
  deleteCouncilSet,
  downloadCouncilSetFile,
  getCouncilDocumentPermissions,
  getCouncilSet,
  getCouncilSetInputCodes,
  listCouncilDownloadLog,
  listCouncilSetDeletions,
  listCouncilSets,
  listCouncilTemplates,
  uploadCouncilTemplate,
  type CouncilLogParams,
  type CouncilSetListParams,
  type UploadCouncilTemplateInput,
} from "@/lib/api/council-documents"
import type {
  CouncilDocumentPermissions,
  CouncilSetCreate,
} from "@/lib/zod/council-documents"
import { downloadBlob } from "@/lib/utils/download-blob"

export const councilDocumentKeys = {
  all: ["council-documents"] as const,
  permissions: () => [...councilDocumentKeys.all, "quyen"] as const,
  templates: () => [...councilDocumentKeys.all, "templates"] as const,
  sets: () => [...councilDocumentKeys.all, "sets"] as const,
  setList: (p: CouncilSetListParams) => [...councilDocumentKeys.sets(), "list", p] as const,
  set: (id: number) => [...councilDocumentKeys.sets(), "detail", id] as const,
  /** DỮ LIỆU CÁ NHÂN — gcTime 0, gỡ khi unmount. */
  inputCodes: (id: number) => [...councilDocumentKeys.all, "ma-ho-so", id] as const,
  downloadLog: (p: CouncilLogParams) => [...councilDocumentKeys.all, "nhat-ky-tai", p] as const,
  deletions: (p: Omit<CouncilLogParams, "set_id">) =>
    [...councilDocumentKeys.all, "nhat-ky-xoa", p] as const,
}

// ── cờ quyền ─────────────────────────────────────────────────────────────────
export const NO_COUNCIL_PERMISSIONS: CouncilDocumentPermissions = {
  xem_mau: false,
  tai_mau_len: false,
  xem_danh_sach_bo: false,
  tao_bo: false,
  xem_chi_tiet_bo: false,
  tai_tep: false,
  xoa_bo: false,
  xem_ma_ho_so: false,
  xem_nhat_ky_tai: false,
  xem_nhat_ky_xoa: false,
}

export type CouncilPermissionState = "loading" | "forbidden" | "error" | "ready"

export interface CouncilPermissionsViewModel {
  state: CouncilPermissionState
  /** luôn đủ khoá; chỉ có giá trị bật khi `state === "ready"` */
  permissions: CouncilDocumentPermissions
  error: unknown
}

export function useCouncilDocumentPermissions(): CouncilPermissionsViewModel {
  const q = useQuery({
    queryKey: councilDocumentKeys.permissions(),
    queryFn: getCouncilDocumentPermissions,
    staleTime: 60_000,
    retry: false,
  })
  return useMemo<CouncilPermissionsViewModel>(() => {
    if (q.isPending) {
      return { state: "loading", permissions: NO_COUNCIL_PERMISSIONS, error: null }
    }
    if (q.isError) {
      const forbidden = axios.isAxiosError(q.error) && q.error.response?.status === 403
      return {
        state: forbidden ? "forbidden" : "error",
        permissions: NO_COUNCIL_PERMISSIONS,
        error: q.error,
      }
    }
    return { state: "ready", permissions: q.data, error: null }
  }, [q.isPending, q.isError, q.error, q.data])
}

// ── kho mẫu ──────────────────────────────────────────────────────────────────
export function useCouncilTemplates(enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.templates(),
    queryFn: listCouncilTemplates,
    enabled,
    staleTime: 30_000,
  })
}

export function useUploadCouncilTemplate() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (input: UploadCouncilTemplateInput) => uploadCouncilTemplate(input),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: councilDocumentKeys.templates() })
    },
  })
}

// ── bộ văn bản ───────────────────────────────────────────────────────────────
export function useCouncilSets(params: CouncilSetListParams, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.setList(params),
    queryFn: () => listCouncilSets(params),
    enabled,
    staleTime: 30_000,
    placeholderData: keepPreviousData,
  })
}

export function useCouncilSet(setId: number, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.set(setId),
    queryFn: () => getCouncilSet(setId),
    enabled: enabled && Number.isInteger(setId) && setId > 0,
    staleTime: 30_000,
  })
}

/**
 * Dựng bộ. `gcTime: 0`: biến số mutation (thân có danh sách mã) rời
 * MutationCache ngay khi không còn ai quan sát. Chống bấm đúp: nút khoá theo
 * `isPending` (máy chủ vẫn là chốt — khoá dựng ⇒ 409).
 */
export function useCreateCouncilSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (payload: CouncilSetCreate) => createCouncilSet(payload),
    gcTime: 0,
    onSuccess: (bo) => {
      qc.setQueryData(councilDocumentKeys.set(bo.id), bo)
      void qc.invalidateQueries({ queryKey: councilDocumentKeys.sets() })
    },
  })
}

export function useDeleteCouncilSet() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ setId, lyDo }: { setId: number; lyDo: string }) =>
      deleteCouncilSet(setId, lyDo),
    gcTime: 0,
    onSuccess: (vet) => {
      qc.removeQueries({ queryKey: councilDocumentKeys.inputCodes(vet.set_id) })
      // Chi tiết bộ: đánh dấu cũ, KHÔNG tải lại ngay (trang đang chuyển đi — tải lại ⇒ 404 nháy).
      void qc.invalidateQueries({
        queryKey: councilDocumentKeys.set(vet.set_id),
        refetchType: "none",
      })
      void qc.invalidateQueries({ queryKey: [...councilDocumentKeys.sets(), "list"] })
      void qc.invalidateQueries({ queryKey: [...councilDocumentKeys.all, "nhat-ky-xoa"] })
    },
  })
}

/**
 * Danh sách mã đầu vào (CHỈ admin) — DỮ LIỆU CÁ NHÂN. Chỉ tải khi `enabled`
 * (người dùng bấm "Hiện"); không giữ trong cache: `gcTime: 0` ⇒ React Query
 * gỡ query ngay khi không còn component nào dùng (bấm "Ẩn" / rời trang). Không
 * thêm `removeQueries` trong cleanup: StrictMode (dev) chạy cleanup giữa hai
 * lần mount ⇒ tải mã HAI lần.
 */
export function useCouncilSetInputCodes(setId: number, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.inputCodes(setId),
    queryFn: () => getCouncilSetInputCodes(setId),
    enabled,
    gcTime: 0,
    staleTime: 0,
    retry: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  })
}

export function useDownloadCouncilSetFile() {
  return useMutation({
    mutationFn: async ({ setId, thuTu }: { setId: number; thuTu: number }) => {
      const tep = await downloadCouncilSetFile(setId, thuTu)
      downloadBlob(tep.blob, tep.filename)
      return tep.filename
    },
    gcTime: 0,
  })
}

// ── nhật ký (CHỈ admin) ──────────────────────────────────────────────────────
export function useCouncilDownloadLog(params: CouncilLogParams, enabled: boolean) {
  return useQuery({
    queryKey: councilDocumentKeys.downloadLog(params),
    queryFn: () => listCouncilDownloadLog(params),
    enabled,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  })
}

export function useCouncilSetDeletions(
  params: Omit<CouncilLogParams, "set_id">,
  enabled: boolean,
) {
  return useQuery({
    queryKey: councilDocumentKeys.deletions(params),
    queryFn: () => listCouncilSetDeletions(params),
    enabled,
    staleTime: 15_000,
    placeholderData: keepPreviousData,
  })
}
